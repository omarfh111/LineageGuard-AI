import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import DesignPreview from "./DesignPreview";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DesignPreview />
  </StrictMode>,
);
