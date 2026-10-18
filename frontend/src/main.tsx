import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useParams } from "react-router-dom";
import { Home } from "./pages/Home";
import { Login, Signup } from "./pages/AuthPages";
import { CasesPage } from "./pages/CasesPage";
import { ProfilePage } from "./pages/ProfilePage";
import { Privacy } from "./pages/Privacy";
import { CasePage } from "./pages/CasePage";
import { BankApp } from "./bank/BankApp";
import { AdminApp } from "./admin/AdminApp";
import { PendingPage } from "./pages/StaffPages";
import { RequireAuth } from "./ui/RequireAuth";
import "./styles.css";

function OldCaseLink() {
  const { caseId } = useParams();
  return <Navigate to={`/cases/${caseId}`} replace />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/login" element={<Login />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/cases" element={<RequireAuth><CasesPage /></RequireAuth>} />
        <Route path="/cases/:caseId" element={<RequireAuth><CasePage /></RequireAuth>} />
        <Route path="/profile" element={<RequireAuth><ProfilePage /></RequireAuth>} />
        <Route path="/case/:caseId" element={<OldCaseLink />} />
        <Route path="/bank/*" element={<BankApp />} />
        <Route path="/pending" element={<PendingPage />} />
        <Route path="/admin/*" element={<AdminApp />} />
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
