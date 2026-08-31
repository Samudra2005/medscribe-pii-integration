import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { AdminDashboard } from "./pages/AdminDashboard";
import { NursePage } from "./pages/NursePage";
import { DoctorPage } from "./pages/DoctorPage";
import { UnauthorizedPage } from "./pages/UnauthorizedPage";
import { RootRedirect } from "./components/RootRedirect";
import { PatientsPage } from "./pages/PatientsPage";
import { UsersPage } from "./pages/UsersPage";
import { HitlPage } from "./pages/HitlPage";
import { AuditLogPage } from "./pages/AuditLogPage";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/change-password"
            element={
              <ProtectedRoute allowPasswordChange>
                <ChangePasswordPage />
              </ProtectedRoute>
            }
          />
                    <Route
            path="/admin"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <AdminDashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/patients"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <PatientsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <UsersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/hitl"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <HitlPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/admin/audit-logs"
            element={
              <ProtectedRoute allowedRoles={["admin"]}>
                <AuditLogPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/nurse"
            element={
              <ProtectedRoute allowedRoles={["nurse"]}>
                <NursePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/nurse/patients"
            element={
              <ProtectedRoute allowedRoles={["nurse"]}>
                <PatientsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/doctor/*"
            element={
              <ProtectedRoute allowedRoles={["doctor"]}>
                <DoctorPage />
              </ProtectedRoute>
            }
          />
          <Route path="/unauthorized" element={<UnauthorizedPage />} />
          <Route path="/" element={<RootRedirect />} />
          <Route path="*" element={<RootRedirect />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;