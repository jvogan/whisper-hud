import Foundation
import Translation

struct Request: Decodable {
    let text: String
    let source: String
    let target: String
}

struct Response: Encodable {
    let text: String
}

struct ErrorResponse: Encodable {
    let error: String
}

@main
struct Main {
    static func main() async {
        let inputData = FileHandle.standardInput.readDataToEndOfFile()
        guard !inputData.isEmpty else {
            writeError("Missing input")
            exit(1)
        }

        do {
            let request = try JSONDecoder().decode(Request.self, from: inputData)
            let sourceLang: Locale.Language
            if request.source == "auto" || request.source == "und" || request.source.isEmpty {
                if let current = Locale.current.language {
                    sourceLang = current
                } else {
                    sourceLang = Locale.Language(identifier: "en")
                }
            } else {
                sourceLang = Locale.Language(identifier: request.source)
            }
            if request.target.isEmpty {
                writeError("Missing target language")
                exit(1)
            }
            let targetLang = Locale.Language(identifier: request.target)

            let session = TranslationSession(installedSource: sourceLang, target: targetLang)
            let result = try await session.translate(request.text)

            let response = Response(text: result.targetText)
            let output = try JSONEncoder().encode(response)
            FileHandle.standardOutput.write(output)
        } catch {
            writeError("\(error)")
            exit(1)
        }
    }

    private static func writeError(_ message: String) {
        if let data = try? JSONEncoder().encode(ErrorResponse(error: message)) {
            FileHandle.standardError.write(data)
        }
    }
}
