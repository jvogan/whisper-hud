"""
Character Pack Creator for WhisperHUD.

A multi-step wizard for creating custom character packs:
- Step 1: Name and description
- Step 2: Upload 4 images (idle, recording, processing, error)
- Step 3: Process images (remove backgrounds)
- Step 4: Preview and save

Uses PyObjC for native macOS UI and Vision framework for background removal.
"""

import threading
from typing import Callable, Optional, Dict

from .logging_config import get_logger

logger = get_logger("pack_creator")

try:
    from AppKit import (
        NSWindow,
        NSView,
        NSButton,
        NSTextField,
        NSColor,
        NSFont,
        NSWindowStyleMaskTitled,
        NSWindowStyleMaskClosable,
        NSBackingStoreBuffered,
        NSScreen,
        NSMakeRect,
        NSBezierPath,
        NSOpenPanel,
        NSApplication,
        NSTextAlignmentCenter,
        NSBezelStyleRounded,
        NSCompositingOperationSourceOver,
        NSZeroRect,
        NSObject,
        NSAlert,
        NSProgressIndicator,
        NSImage,
        NSAlertStyleWarning,
        NSAlertStyleInformational,
    )
    from PyObjCTools import AppHelper
    from objc import super as objc_super

    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False


# States to collect images for
PACK_STATES = ["idle", "recording", "processing", "error"]
STATE_INFO = {
    "idle": {"label": "Idle", "description": "Sleeping, relaxed, peaceful", "example": "Eyes closed, Zzz..."},
    "recording": {
        "label": "Recording",
        "description": "Alert, active, listening",
        "example": "Wide eyes, holding mic/pen",
    },
    "processing": {
        "label": "Processing",
        "description": "Thinking, confused",
        "example": "Question mark, scratching head",
    },
    "error": {"label": "Error", "description": "Distressed, dizzy", "example": "X eyes, stars, fallen over"},
}


def _hex_to_nscolor(hex_color: str) -> "NSColor":
    """Convert hex color string to NSColor."""
    if not HAS_APPKIT:
        return None
    try:
        hex_color = hex_color.lstrip("#")
        if len(hex_color) >= 6:
            r = int(hex_color[0:2], 16) / 255.0
            g = int(hex_color[2:4], 16) / 255.0
            b = int(hex_color[4:6], 16) / 255.0
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
    except Exception:
        pass
    return NSColor.whiteColor()


if HAS_APPKIT:

    class ImagePreviewBox(NSView):
        """A preview box for displaying an uploaded image."""

        def initWithFrame_(self, frame):
            self = objc_super(ImagePreviewBox, self).initWithFrame_(frame)
            if self is None:
                return None

            self._image = None
            self._placeholder_text = "Drop image here"
            self._is_hover = False

            self.setWantsLayer_(True)
            return self

        def setImage_(self, image):
            self._image = image
            self.setNeedsDisplay_(True)

        def setPlaceholderText_(self, text):
            self._placeholder_text = text
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            bounds = self.bounds()

            # Draw border
            border_color = NSColor.colorWithCalibratedWhite_alpha_(0.4, 1.0)
            border_color.setStroke()
            path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, 8, 8)
            path.setLineWidth_(1.0)
            path.stroke()

            # Fill background
            bg_color = NSColor.colorWithCalibratedWhite_alpha_(0.15, 1.0)
            bg_color.setFill()
            path.fill()

            if self._image:
                # Draw the image centered
                img_size = self._image.size()
                scale = min((bounds.size.width - 16) / img_size.width, (bounds.size.height - 16) / img_size.height)
                draw_width = img_size.width * scale
                draw_height = img_size.height * scale
                x = (bounds.size.width - draw_width) / 2
                y = (bounds.size.height - draw_height) / 2

                self._image.drawInRect_fromRect_operation_fraction_(
                    NSMakeRect(x, y, draw_width, draw_height), NSZeroRect, NSCompositingOperationSourceOver, 1.0
                )
            else:
                # Draw placeholder text
                text_color = NSColor.colorWithCalibratedWhite_alpha_(0.5, 1.0)
                text = NSTextField.alloc().initWithFrame_(
                    NSMakeRect(0, bounds.size.height / 2 - 10, bounds.size.width, 20)
                )
                text.setStringValue_(self._placeholder_text)
                text.setAlignment_(NSTextAlignmentCenter)
                text.setFont_(NSFont.systemFontOfSize_(11))
                text.setTextColor_(text_color)
                text.setBezeled_(False)
                text.setDrawsBackground_(False)
                text.setEditable_(False)
                text.setSelectable_(False)

    class WidgetPreviewView(NSView):
        """Preview widget that displays the character icon."""

        def initWithFrame_(self, frame):
            self = objc_super(WidgetPreviewView, self).initWithFrame_(frame)
            if self is None:
                return None

            self._icon = None
            self._bg_color = "#232329"

            self.setWantsLayer_(True)
            return self

        def setIcon_(self, icon):
            self._icon = icon
            self.setNeedsDisplay_(True)

        def setBgColor_(self, color):
            self._bg_color = color
            self.setNeedsDisplay_(True)

        def drawRect_(self, rect):
            bounds = self.bounds()
            size = min(bounds.size.width, bounds.size.height)

            # Center
            x = (bounds.size.width - size) / 2
            y = (bounds.size.height - size) / 2

            # Draw subtle glow/background
            glow_color = _hex_to_nscolor(self._bg_color)
            glow_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                glow_color.redComponent(), glow_color.greenComponent(), glow_color.blueComponent(), 0.3
            )
            glow_color.setFill()
            glow_path = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(x, y, size, size))
            glow_path.fill()

            # Draw icon
            if self._icon:
                icon_rect = NSMakeRect(x + 4, y + 4, size - 8, size - 8)
                self._icon.drawInRect_fromRect_operation_fraction_(
                    icon_rect, NSZeroRect, NSCompositingOperationSourceOver, 1.0
                )

    class PackCreatorDelegate(NSObject):
        """Delegate class to handle UI actions."""

        def initWithCreator_(self, creator):
            self = objc_super(PackCreatorDelegate, self).init()
            if self is None:
                return None
            self._creator = creator
            return self

        def goBack_(self, sender):
            self._creator.handleGoBack()

        def goNext_(self, sender):
            self._creator.handleGoNext()

        def cancel_(self, sender):
            self._creator.handleCancel()

        def save_(self, sender):
            self._creator.handleSave()

        def browseImage_(self, sender):
            self._creator.handleBrowseImage(sender)

        def clearImage_(self, sender):
            self._creator.handleClearImage(sender)

        def nameChanged_(self, sender):
            self._creator.handleNameChanged(sender)


class PackCreatorWindow:
    """
    Character pack creator window with multi-step wizard.
    """

    def __init__(self, image_processor, pack_manager, on_save: Callable, on_cancel: Callable):
        self._image_processor = image_processor
        self._pack_manager = pack_manager
        self._on_save = on_save
        self._on_cancel = on_cancel

        self._window: Optional[NSWindow] = None
        self._current_step = 1
        self._max_steps = 4

        # Pack data
        self._pack_name = ""
        self._pack_description = ""
        self._pack_id = ""

        # Source images (original paths)
        self._source_images: Dict[str, str] = {}

        # Processed images (NSImage with background removed)
        self._processed_images: Dict[str, "NSImage"] = {}

        # Processing status
        self._processing_complete = False
        self._processing_cancelled = False
        self._processing_errors: Dict[str, str] = {}

        # UI elements
        self._name_field = None
        self._desc_field = None
        self._image_previews: Dict[str, "ImagePreviewBox"] = {}
        self._browse_buttons: Dict[str, "NSButton"] = {}
        self._progress_bar = None
        self._status_label = None
        self._widget_previews: Dict[str, "WidgetPreviewView"] = {}

        # Delegate
        self._delegate = None

    def show(self):
        """Show the creator window."""
        if not HAS_APPKIT:
            logger.error("AppKit not available, cannot show pack creator")
            return

        def _create_and_show():
            self._create_window()
            self._show_step(1)
            self._window.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        AppHelper.callAfter(_create_and_show)

    def _create_window(self):
        """Create the creator window."""
        self._delegate = PackCreatorDelegate.alloc().initWithCreator_(self)

        width, height = 680, 560

        screen = NSScreen.mainScreen()
        if screen:
            screen_rect = screen.visibleFrame()
            x = screen_rect.origin.x + (screen_rect.size.width - width) / 2
            y = screen_rect.origin.y + (screen_rect.size.height - height) / 2
        else:
            x, y = 100, 100

        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Create Character Pack")
        self._window.setReleasedWhenClosed_(False)

    def _clear_content(self):
        """Clear the window content."""
        if self._window:
            content = self._window.contentView()
            for subview in list(content.subviews()):
                subview.removeFromSuperview()

    def _show_step(self, step: int):
        """Show a specific step of the wizard."""
        self._current_step = step
        self._clear_content()

        if step == 1:
            self._build_name_step()
        elif step == 2:
            self._build_upload_step()
        elif step == 3:
            self._build_process_step()
        elif step == 4:
            self._build_preview_step()

    def _build_name_step(self):
        """Build Step 1: Name and description."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = self._create_label(
            NSMakeRect(20, height - 50, width - 40, 30), "Step 1: Name Your Pack", bold=True, size=18
        )
        content.addSubview_(title)

        # Subtitle
        subtitle = self._create_label(
            NSMakeRect(20, height - 75, width - 40, 20),
            "Give your character pack a unique name and description",
            size=12,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(subtitle)

        # Pack name field
        name_label = self._create_label(NSMakeRect(20, height - 130, 100, 24), "Pack Name:")
        content.addSubview_(name_label)

        self._name_field = NSTextField.alloc().initWithFrame_(NSMakeRect(130, height - 130, 400, 24))
        self._name_field.setStringValue_(self._pack_name)
        self._name_field.setPlaceholderString_("e.g., My Custom Cat")
        self._name_field.setTarget_(self._delegate)
        self._name_field.setAction_("nameChanged:")
        content.addSubview_(self._name_field)

        # Pack ID (auto-generated) preview
        id_label = self._create_label(NSMakeRect(20, height - 165, 100, 24), "Pack ID:")
        content.addSubview_(id_label)

        self._id_preview = self._create_label(
            NSMakeRect(130, height - 165, 400, 24),
            self._generate_pack_id(self._pack_name) or "(generated from name)",
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(self._id_preview)

        # Description field
        desc_label = self._create_label(NSMakeRect(20, height - 210, 100, 24), "Description:")
        content.addSubview_(desc_label)

        self._desc_field = NSTextField.alloc().initWithFrame_(NSMakeRect(130, height - 250, 400, 60))
        self._desc_field.setStringValue_(self._pack_description)
        self._desc_field.setPlaceholderString_("A brief description of your character pack...")
        content.addSubview_(self._desc_field)

        # Background removal info
        method_label = self._create_label(
            NSMakeRect(20, height - 310, width - 40, 20),
            f"Background removal: {self._image_processor.get_background_removal_method()}",
            size=11,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(method_label)

        # Navigation
        self._add_navigation_buttons(content, height, show_back=False, show_next=True)

    def _build_upload_step(self):
        """Build Step 2: Upload images."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = self._create_label(
            NSMakeRect(20, height - 50, width - 40, 30), "Step 2: Upload Images", bold=True, size=18
        )
        content.addSubview_(title)

        # Subtitle
        subtitle = self._create_label(
            NSMakeRect(20, height - 75, width - 40, 20),
            "Select an image for each widget state. Backgrounds will be removed automatically.",
            size=12,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(subtitle)

        # Image upload grid (2x2)
        x_positions = [30, 350]
        y_positions = [height - 280, height - 480]

        states_grid = [["idle", "recording"], ["processing", "error"]]

        self._image_previews = {}
        self._browse_buttons = {}

        for row_idx, row in enumerate(states_grid):
            for col_idx, state in enumerate(row):
                x = x_positions[col_idx]
                y = y_positions[row_idx]

                info = STATE_INFO[state]

                # State label
                state_label = self._create_label(
                    NSMakeRect(x, y + 130, 280, 20), f"{info['label']} - {info['description']}", bold=True, size=12
                )
                content.addSubview_(state_label)

                # Example text
                example = self._create_label(
                    NSMakeRect(x, y + 110, 280, 18),
                    f"Example: {info['example']}",
                    size=10,
                    color=NSColor.secondaryLabelColor(),
                )
                content.addSubview_(example)

                # Image preview box
                preview = ImagePreviewBox.alloc().initWithFrame_(NSMakeRect(x, y, 100, 100))
                preview.setPlaceholderText_("No image")
                if state in self._source_images:
                    img = NSImage.alloc().initWithContentsOfFile_(self._source_images[state])
                    preview.setImage_(img)
                content.addSubview_(preview)
                self._image_previews[state] = preview

                # Browse button
                browse_btn = NSButton.alloc().initWithFrame_(NSMakeRect(x + 110, y + 60, 80, 28))
                browse_btn.setTitle_("Browse...")
                browse_btn.setBezelStyle_(NSBezelStyleRounded)
                browse_btn.setTarget_(self._delegate)
                browse_btn.setAction_("browseImage:")
                browse_btn.setTag_(hash(state) & 0x7FFFFFFF)
                content.addSubview_(browse_btn)
                self._browse_buttons[state] = browse_btn

                # Clear button
                clear_btn = NSButton.alloc().initWithFrame_(NSMakeRect(x + 110, y + 30, 80, 28))
                clear_btn.setTitle_("Clear")
                clear_btn.setBezelStyle_(NSBezelStyleRounded)
                clear_btn.setTarget_(self._delegate)
                clear_btn.setAction_("clearImage:")
                clear_btn.setTag_(hash(state) & 0x7FFFFFFF)
                content.addSubview_(clear_btn)

        # Navigation
        self._add_navigation_buttons(content, height, show_back=True, show_next=True)

    def _build_process_step(self):
        """Build Step 3: Process images."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = self._create_label(
            NSMakeRect(20, height - 50, width - 40, 30), "Step 3: Processing Images", bold=True, size=18
        )
        content.addSubview_(title)

        # Subtitle
        subtitle = self._create_label(
            NSMakeRect(20, height - 75, width - 40, 20),
            "Removing backgrounds from your images...",
            size=12,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(subtitle)

        # Progress bar
        self._progress_bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(40, height - 130, width - 80, 20))
        self._progress_bar.setIndeterminate_(False)
        self._progress_bar.setMinValue_(0)
        self._progress_bar.setMaxValue_(len(PACK_STATES))
        self._progress_bar.setDoubleValue_(0)
        content.addSubview_(self._progress_bar)

        # Status label
        self._status_label = self._create_label(NSMakeRect(40, height - 170, width - 80, 24), "Starting...", size=13)
        content.addSubview_(self._status_label)

        # Results area
        self._results_area = NSView.alloc().initWithFrame_(NSMakeRect(40, height - 400, width - 80, 200))
        content.addSubview_(self._results_area)

        # Navigation (disabled during processing)
        self._add_navigation_buttons(content, height, show_back=True, show_next=True, next_enabled=False)

        # Start processing
        self._start_processing()

    def _build_preview_step(self):
        """Build Step 4: Preview and save."""
        content = self._window.contentView()
        width = self._window.frame().size.width
        height = self._window.frame().size.height

        # Title
        title = self._create_label(
            NSMakeRect(20, height - 50, width - 40, 30), "Step 4: Preview & Save", bold=True, size=18
        )
        content.addSubview_(title)

        # Subtitle
        subtitle = self._create_label(
            NSMakeRect(20, height - 75, width - 40, 20),
            f"Preview your '{self._pack_name}' character pack at different widget sizes",
            size=12,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(subtitle)

        # Widget size previews
        sizes = [("Small", 24), ("Medium", 32), ("Large", 44), ("XLarge", 56)]

        x_pos = 40
        for size_name, size_px in sizes:
            # Size label
            size_label = self._create_label(NSMakeRect(x_pos, height - 120, 120, 20), size_name, bold=True, size=12)
            content.addSubview_(size_label)

            # State previews
            y_pos = height - 160
            for state in PACK_STATES:
                if state in self._processed_images and self._processed_images[state]:
                    preview = WidgetPreviewView.alloc().initWithFrame_(
                        NSMakeRect(x_pos, y_pos, size_px + 16, size_px + 16)
                    )
                    preview.setIcon_(self._processed_images[state])
                    content.addSubview_(preview)

                state_label = self._create_label(
                    NSMakeRect(x_pos + size_px + 20, y_pos + (size_px // 2) - 8, 80, 16),
                    STATE_INFO[state]["label"],
                    size=10,
                    color=NSColor.secondaryLabelColor(),
                )
                content.addSubview_(state_label)

                y_pos -= size_px + 30

            x_pos += 150

        # Pack info summary
        summary_y = 120
        info_label = self._create_label(
            NSMakeRect(40, summary_y, width - 80, 20), f"Pack: {self._pack_name}", bold=True, size=13
        )
        content.addSubview_(info_label)

        id_label = self._create_label(
            NSMakeRect(40, summary_y - 25, width - 80, 20),
            f"ID: {self._pack_id}",
            size=11,
            color=NSColor.secondaryLabelColor(),
        )
        content.addSubview_(id_label)

        if self._pack_description:
            desc_label = self._create_label(
                NSMakeRect(40, summary_y - 50, width - 80, 20),
                self._pack_description,
                size=11,
                color=NSColor.secondaryLabelColor(),
            )
            content.addSubview_(desc_label)

        # Navigation
        self._add_navigation_buttons(content, height, show_back=True, show_next=False, show_save=True)

    def _create_label(self, frame, text, bold=False, size=13, color=None):
        """Create a label with common settings."""
        label = NSTextField.alloc().initWithFrame_(frame)
        label.setStringValue_(text)
        label.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
        if color:
            label.setTextColor_(color)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setEditable_(False)
        label.setSelectable_(False)
        return label

    def _add_navigation_buttons(
        self,
        content,
        height,
        show_back=True,
        show_next=True,
        show_save=False,
        next_enabled=True,
    ):
        """Add navigation buttons at the bottom."""
        y = 20

        # Cancel button
        cancel_btn = NSButton.alloc().initWithFrame_(NSMakeRect(20, y, 80, 32))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(NSBezelStyleRounded)
        cancel_btn.setTarget_(self._delegate)
        cancel_btn.setAction_("cancel:")
        content.addSubview_(cancel_btn)

        if show_back:
            back_btn = NSButton.alloc().initWithFrame_(NSMakeRect(480, y, 80, 32))
            back_btn.setTitle_("Back")
            back_btn.setBezelStyle_(NSBezelStyleRounded)
            back_btn.setTarget_(self._delegate)
            back_btn.setAction_("goBack:")
            content.addSubview_(back_btn)

        if show_next:
            self._next_btn = NSButton.alloc().initWithFrame_(NSMakeRect(580, y, 80, 32))
            self._next_btn.setTitle_("Next")
            self._next_btn.setBezelStyle_(NSBezelStyleRounded)
            self._next_btn.setKeyEquivalent_("\r")
            self._next_btn.setTarget_(self._delegate)
            self._next_btn.setAction_("goNext:")
            self._next_btn.setEnabled_(next_enabled)
            content.addSubview_(self._next_btn)

        if show_save:
            save_btn = NSButton.alloc().initWithFrame_(NSMakeRect(580, y, 80, 32))
            save_btn.setTitle_("Save")
            save_btn.setBezelStyle_(NSBezelStyleRounded)
            save_btn.setKeyEquivalent_("\r")
            save_btn.setTarget_(self._delegate)
            save_btn.setAction_("save:")
            content.addSubview_(save_btn)

    def _generate_pack_id(self, name: str) -> str:
        """Generate a pack ID from name."""
        if not name:
            return ""
        # Convert to lowercase, replace spaces with dashes, remove non-alphanumeric
        pack_id = name.lower().strip()
        pack_id = pack_id.replace(" ", "-")
        pack_id = "".join(c for c in pack_id if c.isalnum() or c == "-")
        # Remove consecutive dashes
        while "--" in pack_id:
            pack_id = pack_id.replace("--", "-")
        return pack_id.strip("-")

    def _start_processing(self):
        """Start background processing of images."""
        self._processing_complete = False
        self._processing_errors = {}
        self._processed_images = {}
        self._processing_cancelled = False

        def process_images():
            # Copy source images to avoid race conditions
            source_images = dict(self._source_images)

            for i, state in enumerate(PACK_STATES):
                # Check if window was closed
                if self._processing_cancelled or self._window is None:
                    return

                # Update UI on main thread
                def update_status(s=state, idx=i):
                    # Check window validity before UI updates
                    if self._window is None or self._processing_cancelled:
                        return
                    if self._status_label:
                        self._status_label.setStringValue_(f"Processing {STATE_INFO[s]['label']}...")
                    if self._progress_bar:
                        self._progress_bar.setDoubleValue_(idx)

                AppHelper.callAfter(update_status)

                if state not in source_images:
                    self._processing_errors[state] = "No image selected"
                    continue

                path = source_images[state]
                try:
                    # Remove background
                    result = self._image_processor.remove_background(path, 128)
                    if result:
                        self._processed_images[state] = result
                    else:
                        # Fall back to loading original with alpha
                        img = NSImage.alloc().initWithContentsOfFile_(path)
                        if img:
                            from .image_processor import crop_preserving_alpha

                            self._processed_images[state] = crop_preserving_alpha(img, 128)
                        if state not in self._processed_images or self._processed_images[state] is None:
                            self._processing_errors[state] = "Failed to process image"
                except Exception as e:
                    logger.error(f"Error processing {state}: {e}")
                    self._processing_errors[state] = str(e)

            # Complete
            def on_complete():
                # Check window validity before UI updates
                if self._window is None or self._processing_cancelled:
                    return

                self._processing_complete = True
                if self._progress_bar:
                    self._progress_bar.setDoubleValue_(len(PACK_STATES))

                if self._processing_errors:
                    error_msg = ", ".join(f"{STATE_INFO[s]['label']}: {e}" for s, e in self._processing_errors.items())
                    if self._status_label:
                        self._status_label.setStringValue_(f"Completed with errors: {error_msg}")
                else:
                    if self._status_label:
                        self._status_label.setStringValue_("Processing complete!")

                # Enable next button
                if hasattr(self, "_next_btn") and self._next_btn:
                    # Only enable if we have all required images
                    all_present = all(s in self._processed_images for s in PACK_STATES)
                    self._next_btn.setEnabled_(all_present)

            AppHelper.callAfter(on_complete)

        # Run in background thread
        thread = threading.Thread(target=process_images, daemon=True)
        thread.start()

    # Action handlers
    def handleGoBack(self):
        """Go to previous step."""
        if self._current_step > 1:
            self._show_step(self._current_step - 1)

    def handleGoNext(self):
        """Go to next step."""
        # Validate current step
        if self._current_step == 1:
            # Validate name
            name = self._name_field.stringValue().strip()
            if not name:
                self._show_alert("Name Required", "Please enter a name for your character pack.")
                return
            self._pack_name = name
            self._pack_description = self._desc_field.stringValue().strip()
            self._pack_id = self._generate_pack_id(name)

            # Check if pack ID already exists
            from .character_packs import pack_id_exists

            if pack_id_exists(self._pack_id):
                self._show_alert(
                    "Pack Exists", f"A pack with ID '{self._pack_id}' already exists. Please choose a different name."
                )
                return

        elif self._current_step == 2:
            # Validate all images are selected
            missing = [STATE_INFO[s]["label"] for s in PACK_STATES if s not in self._source_images]
            if missing:
                self._show_alert("Images Required", f"Please select images for: {', '.join(missing)}")
                return

        elif self._current_step == 3:
            # Validate processing complete
            if not self._processing_complete:
                return
            missing = [STATE_INFO[s]["label"] for s in PACK_STATES if s not in self._processed_images]
            if missing:
                self._show_alert("Processing Failed", f"Failed to process images for: {', '.join(missing)}")
                return

        if self._current_step < self._max_steps:
            self._show_step(self._current_step + 1)

    def handleCancel(self):
        """Cancel and close."""
        self._processing_cancelled = True
        self._window.close()
        self._window = None
        if self._on_cancel:
            self._on_cancel()

    def handleSave(self):
        """Save the pack."""
        from .character_packs import save_user_pack

        success, result = save_user_pack(
            self._pack_id, self._pack_name, self._pack_description, self._processed_images, self._image_processor
        )

        if success:
            self._window.close()
            if self._on_save:
                self._on_save(self._pack_id)

            # Show success message
            alert = NSAlert.alloc().init()
            alert.setMessageText_("Pack Created!")
            alert.setInformativeText_(
                f"Your character pack '{self._pack_name}' has been created.\n\n"
                f"You can now select it from Settings > Appearance > Character Packs."
            )
            alert.setAlertStyle_(NSAlertStyleInformational)
            alert.runModal()
        else:
            self._show_alert("Save Failed", result)

    def handleBrowseImage(self, sender):
        """Handle browse button click."""
        # Find which state this is for
        state = None
        for s, btn in self._browse_buttons.items():
            if btn == sender or hash(s) & 0x7FFFFFFF == sender.tag():
                state = s
                break

        if not state:
            return

        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["png", "jpg", "jpeg", "gif", "heic", "webp", "tiff", "bmp"])
        panel.setTitle_(f"Select {STATE_INFO[state]['label']} Image")

        if panel.runModal() == 1:
            url = panel.URL()
            if url:
                path = url.path()

                # Validate
                is_valid, error = self._image_processor.validate_image(path)
                if not is_valid:
                    self._show_alert("Invalid Image", error)
                    return

                # Store path and update preview
                self._source_images[state] = path
                if state in self._image_previews:
                    img = NSImage.alloc().initWithContentsOfFile_(path)
                    self._image_previews[state].setImage_(img)

    def handleClearImage(self, sender):
        """Handle clear button click."""
        state = None
        for s in PACK_STATES:
            if hash(s) & 0x7FFFFFFF == sender.tag():
                state = s
                break

        if state and state in self._source_images:
            del self._source_images[state]
            if state in self._image_previews:
                self._image_previews[state].setImage_(None)

    def handleNameChanged(self, sender):
        """Handle name field change."""
        name = sender.stringValue().strip()
        pack_id = self._generate_pack_id(name)
        if hasattr(self, "_id_preview") and self._id_preview:
            self._id_preview.setStringValue_(pack_id or "(generated from name)")

    def _show_alert(self, title: str, message: str):
        """Show an alert dialog."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.setAlertStyle_(NSAlertStyleWarning)
        alert.runModal()


def show_pack_creator(image_processor, pack_manager, on_save: Callable = None, on_cancel: Callable = None):
    """
    Show the pack creator window.

    Args:
        image_processor: ImageProcessor instance
        pack_manager: CharacterPackManager instance
        on_save: Callback when saved (receives pack_id)
        on_cancel: Callback when cancelled

    Returns:
        PackCreatorWindow instance
    """
    if not HAS_APPKIT:
        logger.error("AppKit not available, cannot show pack creator")
        return None

    creator = PackCreatorWindow(image_processor, pack_manager, on_save, on_cancel)
    creator.show()
    return creator
