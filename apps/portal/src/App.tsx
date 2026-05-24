import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import Login from "./components/Login";
import { useAuth } from "./hooks/useAuth";
import Catalog from "./pages/Catalog";
import Compliance from "./pages/Compliance";
import Instances from "./pages/Instances";
import ProvisionWizard from "./pages/ProvisionWizard";

export default function App() {
  const { auth } = useAuth();
  if (!auth) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Catalog />} />
        <Route path="/provision/:serviceId" element={<ProvisionWizard />} />
        <Route path="/instances" element={<Instances />} />
        <Route path="/compliance" element={<Compliance />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
