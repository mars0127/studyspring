# Design system workflow

StudySpring uses a calm, accessible learning interface. Keep Figma and Streamlit aligned through reusable patterns rather than page-specific CSS.

- Typography: page title, section heading, body, caption; never use caption as the only label.
- Spacing: 8, 16, 24, and 32 px rhythm. Cards use consistent padding and modest rounded corners.
- Surfaces: page background, card surface, and clearly separated success/warning/error states.
- Buttons: one primary action per screen; destructive actions require confirmation.
- Inputs: visible labels, adjacent errors, keyboard-accessible controls, sufficient contrast, and clear loading/empty states.
- Narrow layouts: stack columns, keep touch targets practical, and avoid crowded sidebars.

Use Unicode or Streamlit-native icons today. Lucide and component-library conventions are reserved for a future React migration.
