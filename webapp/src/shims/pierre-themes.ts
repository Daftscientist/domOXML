// @pierre/diffs resolves themes through `@pierre/theming/themes`, whose
// default registry also pulls in every Shiki theme. The app only uses the
// two Pierre themes, so Vite aliases the entry to a collection containing
// just the first-party Pierre themes, built with the package's own
// collection machinery.
import { createThemeCollection } from "../../node_modules/@pierre/theming/dist/modules/createThemeCollection.js";
import { pierreThemes } from "../../node_modules/@pierre/theming/dist/collections/pierre.js";

export const themes = createThemeCollection({ themes: [pierreThemes] });
