FlowSwitch UI refinement follow-up

This build centers the field labels, increases control padding, and adds a subtle breathing animation to the monitor outline. It retains the existing Tk/ttk widget toolkit and existing connection/clipboard/file-transfer code.

Note: ttk widgets do not support genuinely rounded entry/button corners consistently across platforms. This update softens spacing but does not claim fully custom rounded controls. A true rounded UI would require custom Canvas widgets or a themed UI toolkit and should be implemented as a separate visual layer with testing on Windows and macOS.
