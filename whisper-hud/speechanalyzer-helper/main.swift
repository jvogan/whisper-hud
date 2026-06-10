// WhisperHUD SpeechAnalyzer helper.
//
// On-device transcription via macOS 26's SpeechAnalyzer / SpeechTranscriber
// (the modern, Neural Engine accelerated replacement for SFSpeechRecognizer).
// That API is Swift-only, so the Python app drives this tiny single-file binary
// the same way it drives the Apple Translation helper: a JSON request on stdin,
// line-delimited JSON events on stdout.
//
// Protocol
//   stdin  (one JSON object): {"audio_path": "...", "locale": "en-US",
//                              "vocabulary": ["Kubernetes", ...]}   // vocabulary optional
//   stdout (line-delimited JSON, one event per line):
//     {"type":"partial","text":"..."}            // volatile/in-progress hypotheses
//     {"type":"final","text":"...","locale":"en-US"}   // exactly one, last
//   on failure:
//     {"type":"error","message":"..."}           // then exit(nonzero)
//
// The binary fails gracefully with a JSON error on macOS < 26 (the Speech
// SpeechAnalyzer symbols are gated behind @available(macOS 26.0, *)).

import AVFoundation
import Foundation
import Speech

// MARK: - Wire types

struct HelperRequest: Decodable {
    let audioPath: String
    let locale: String?
    let vocabulary: [String]?

    enum CodingKeys: String, CodingKey {
        case audioPath = "audio_path"
        case locale
        case vocabulary
    }
}

// Events are emitted by hand (one compact JSON line each) so partials can be
// flushed immediately as they arrive rather than buffered into one document.

/// Serialize a JSON string value with the minimal required escaping.
private func jsonEscape(_ value: String) -> String {
    var out = ""
    out.reserveCapacity(value.count + 2)
    for scalar in value.unicodeScalars {
        switch scalar {
        case "\"": out += "\\\""
        case "\\": out += "\\\\"
        case "\n": out += "\\n"
        case "\r": out += "\\r"
        case "\t": out += "\\t"
        default:
            if scalar.value < 0x20 {
                out += String(format: "\\u%04x", scalar.value)
            } else {
                out.unicodeScalars.append(scalar)
            }
        }
    }
    return out
}

private func emit(_ line: String) {
    FileHandle.standardOutput.write(Data((line + "\n").utf8))
}

private func emitPartial(_ text: String) {
    emit("{\"type\":\"partial\",\"text\":\"\(jsonEscape(text))\"}")
}

private func emitFinal(_ text: String, locale: String) {
    emit("{\"type\":\"final\",\"text\":\"\(jsonEscape(text))\",\"locale\":\"\(jsonEscape(locale))\"}")
}

/// Emit a terminal error event on stdout and exit nonzero.
private func fail(_ message: String) -> Never {
    emit("{\"type\":\"error\",\"message\":\"\(jsonEscape(message))\"}")
    exit(1)
}

// MARK: - Entry point

@main
struct Main {
    // Bound how long we wait for a locale asset to download before giving up,
    // so a missing/slow model never hangs the dictation pipeline forever. The
    // Python side also enforces its own (larger) subprocess timeout.
    static let assetInstallTimeoutSeconds: UInt64 = 90

    static func main() async {
        let inputData = FileHandle.standardInput.readDataToEndOfFile()
        guard !inputData.isEmpty else {
            fail("Missing input request on stdin")
        }

        let request: HelperRequest
        do {
            request = try JSONDecoder().decode(HelperRequest.self, from: inputData)
        } catch {
            fail("Invalid request JSON: \(error)")
        }

        if #available(macOS 26.0, *) {
            await Runner.run(request)
        } else {
            fail("Apple Speech (Advanced) requires macOS 26 or later (SpeechAnalyzer is unavailable on this system).")
        }
    }
}

// MARK: - macOS 26 SpeechAnalyzer pipeline

@available(macOS 26.0, *)
enum Runner {
    static func run(_ request: HelperRequest) async {
        let audioURL = URL(fileURLWithPath: request.audioPath)
        guard FileManager.default.fileExists(atPath: audioURL.path) else {
            fail("Audio file not found: \(request.audioPath)")
        }

        // Resolve the requested locale, falling back to the system locale.
        let requestedLocale: Locale
        if let raw = request.locale, !raw.isEmpty {
            requestedLocale = Locale(identifier: raw)
        } else {
            requestedLocale = Locale.current
        }

        guard SpeechTranscriber.isAvailable else {
            fail("SpeechTranscriber is not available on this device.")
        }

        // Find the closest supported locale (e.g. map "en" -> "en-US"). If the
        // SDK reports no equivalent, surface a clear, actionable error.
        guard let locale = await SpeechTranscriber.supportedLocale(equivalentTo: requestedLocale) else {
            let supported = await supportedLocaleIdentifiers()
            fail("Locale '\(requestedLocale.identifier)' is not supported by SpeechAnalyzer. Supported locales: \(supported)")
        }

        // Build a transcriber that reports volatile (partial) results in
        // addition to finals so a future streaming wave can surface them live.
        let transcriber = SpeechTranscriber(
            locale: locale,
            transcriptionOptions: [],
            reportingOptions: [.volatileResults],
            attributeOptions: []
        )

        // Ensure the on-device model assets for this locale are installed. If
        // not, request installation with a bounded wait and report progress as
        // a clear error rather than blocking dictation indefinitely.
        do {
            try await ensureModelInstalled(for: transcriber, locale: locale)
        } catch let error as AssetError {
            fail(error.message)
        } catch {
            fail("Failed to prepare on-device model for '\(locale.identifier)': \(error)")
        }

        // Apply user vocabulary as contextual biasing strings when supported.
        let analysisContext = AnalysisContext()
        if let vocabulary = request.vocabulary, !vocabulary.isEmpty {
            let phrases = vocabulary
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            if !phrases.isEmpty {
                analysisContext.contextualStrings = [.general: phrases]
            }
        }

        // Open the audio file. SpeechAnalyzer reads AVAudioFile input directly
        // and converts formats internally as needed.
        let audioFile: AVAudioFile
        do {
            audioFile = try AVAudioFile(forReading: audioURL)
        } catch {
            fail("Could not open audio file: \(error)")
        }

        // Consume results concurrently with analysis. Volatile results are
        // emitted as partials; the most recent text from each finalized range
        // is concatenated into the final transcript.
        var finalizedText = ""
        let resultsTask = Task { () -> String in
            var assembled = ""
            do {
                for try await result in transcriber.results {
                    let text = String(result.text.characters)
                    if result.isFinal {
                        // Finalized ranges arrive in order; append them.
                        if !text.isEmpty {
                            if !assembled.isEmpty && !assembled.hasSuffix(" ") {
                                assembled += " "
                            }
                            assembled += text
                        }
                    } else {
                        // Volatile hypothesis for the not-yet-final tail.
                        let preview = (assembled.isEmpty ? text : assembled + " " + text)
                            .trimmingCharacters(in: .whitespacesAndNewlines)
                        if !preview.isEmpty {
                            emitPartial(preview)
                        }
                    }
                }
            } catch {
                // Surface as a stream error; main flow turns it into an error event.
                throw error
            }
            return assembled.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        do {
            // Build a plain analyzer (NOT the inputAudioFile convenience init,
            // which auto-starts the file and would double-drive analysis when
            // combined with analyzeSequence(from:), tripping a runtime trap).
            let analyzer = SpeechAnalyzer(modules: [transcriber], options: nil)
            // Apply vocabulary biasing context before analysis begins.
            try await analyzer.setContext(analysisContext)
            // Drive analysis to the end of the file, then flush + finish so the
            // results sequence terminates and resultsTask completes.
            _ = try await analyzer.analyzeSequence(from: audioFile)
            try await analyzer.finalizeAndFinishThroughEndOfInput()
        } catch {
            resultsTask.cancel()
            fail("Transcription failed: \(error)")
        }

        do {
            finalizedText = try await resultsTask.value
        } catch {
            fail("Transcription stream failed: \(error)")
        }

        emitFinal(finalizedText, locale: locale.identifier(.bcp47))
    }

    /// Identifiers of every locale SpeechTranscriber supports, for diagnostics.
    static func supportedLocaleIdentifiers() async -> String {
        let locales = await SpeechTranscriber.supportedLocales
        return locales.map { $0.identifier(.bcp47) }.sorted().joined(separator: ", ")
    }

    struct AssetError: Error {
        let message: String
    }

    /// Ensure the model assets backing `transcriber` for `locale` are installed,
    /// requesting a download (bounded by a timeout) when they are not.
    static func ensureModelInstalled(for transcriber: SpeechTranscriber, locale: Locale) async throws {
        let installed = await SpeechTranscriber.installedLocales
        let alreadyInstalled = installed.contains { $0.identifier(.bcp47) == locale.identifier(.bcp47) }
        if alreadyInstalled {
            return
        }

        let status = await AssetInventory.status(forModules: [transcriber])
        if status == .installed {
            return
        }

        guard let installRequest = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) else {
            // No request object means nothing to install — treat as ready.
            return
        }

        // Download with a bounded wait: if it does not finish in time, tell the
        // user it is downloading so they can retry once it completes.
        let downloadTask = Task {
            try await installRequest.downloadAndInstall()
        }
        let timeoutTask = Task { () -> Void in
            try await Task.sleep(nanoseconds: Main.assetInstallTimeoutSeconds * 1_000_000_000)
            downloadTask.cancel()
        }

        do {
            try await downloadTask.value
            timeoutTask.cancel()
        } catch {
            timeoutTask.cancel()
            let finalStatus = await AssetInventory.status(forModules: [transcriber])
            if finalStatus == .installed {
                return
            }
            throw AssetError(
                message: "The on-device speech model for '\(locale.identifier(.bcp47))' is downloading. "
                    + "Please try again once the language model finishes installing "
                    + "(System Settings > General > Language & Region)."
            )
        }
    }
}
