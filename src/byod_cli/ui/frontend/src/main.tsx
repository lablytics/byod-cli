import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import "./index.css";

const Home = lazy(() => import("./pages/Home").then((m) => ({ default: m.Home })));
const Submit = lazy(() => import("./pages/Submit").then((m) => ({ default: m.Submit })));
const Jobs = lazy(() => import("./pages/Jobs").then((m) => ({ default: m.Jobs })));
const JobDetail = lazy(() => import("./pages/JobDetail").then((m) => ({ default: m.JobDetail })));
const SetupWizard = lazy(() => import("./pages/SetupWizard").then((m) => ({ default: m.SetupWizard })));
const Settings = lazy(() => import("./pages/Settings").then((m) => ({ default: m.Settings })));

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Suspense fallback={null}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Home />} />
            <Route path="/submit" element={<Submit />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:jobId" element={<JobDetail />} />
            <Route path="/setup" element={<SetupWizard />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  </React.StrictMode>
);
