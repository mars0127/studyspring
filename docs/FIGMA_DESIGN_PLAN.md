# StudySpring Figma design plan

## Discovery

- The StudySpring Figma file contained one blank frame and no local variables or styles.
- The current Streamlit application uses a calm, academic palette: green primary (`#2F855A`), blue secondary (`#2B6CB0`), light grey background (`#F7FAFC`), white surfaces, and dark navy text.
- The file has the Figma Simple Design System library enabled. Its Button, Card, Navigation, and Input components are suitable for the initial screens.

## Locked v1 scope

- Design foundations: colour, spacing, radii, typography, focus state, and a light shadow.
- Screens: Home/dashboard, Course Library, and textbook import.
- Components: navigation, primary and secondary action treatment, course cards, progress cards, and upload states.

## Code-to-design mapping

| Code token | Figma semantic name | Purpose |
| --- | --- | --- |
| `#2F855A` | `color/brand/primary` | Main actions and active state |
| `#2B6CB0` | `color/brand/secondary` | Links and focus state |
| `#F7FAFC` | `color/bg/page` | Page background |
| `#FFFFFF` | `color/bg/surface` | Cards and panels |
| `#D9E2EC` | `color/border/default` | Borders |
| `#172B4D` | `color/text/primary` | Headings and body copy |
| `#52606D` | `color/text/secondary` | Supporting copy |

## Gap analysis

- New in Figma: all local StudySpring tokens, styles, and product screens.
- Existing in Figma: a linked Simple Design System component library.
- No conflicts exist because the file was blank.
