import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "./site/landing.css";
import Root from "./site/Root";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
