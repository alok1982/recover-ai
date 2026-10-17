import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Landing } from "./pages/Landing";
import { CasePage } from "./pages/CasePage";
import { BankApp } from "./bank/BankApp";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/case/:caseId" element={<CasePage />} />
        <Route path="/bank/*" element={<BankApp />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
