import { Link, Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { pageVariants } from "../animations/variants";

const navLinks = [
  { to: "/", label: "Home", match: (p: string) => p === "/" },
  { to: "/submit", label: "Submit Job", match: (p: string) => p.startsWith("/submit") },
  { to: "/jobs", label: "Jobs", match: (p: string) => p.startsWith("/jobs") },
  { to: "/setup", label: "Setup", match: (p: string) => p.startsWith("/setup") },
  { to: "/settings", label: "Settings", match: (p: string) => p.startsWith("/settings") },
];

export function Layout() {
  const location = useLocation();

  return (
    <div>
      <header
        style={{
          borderBottom: "1px solid var(--border)",
          padding: "12px 24px",
          display: "flex",
          alignItems: "center",
          gap: "32px",
          background: "var(--bg)",
          position: "sticky",
          top: 0,
          zIndex: 100,
        }}
      >
        <div
          style={{
            fontWeight: 800,
            fontSize: "18px",
            letterSpacing: "-0.5px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
            <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10 10-4.5 10-10S17.5 2 12 2" />
            <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
            <path d="M2 12h20" />
          </svg>
          BYOD
          <span style={{ color: "var(--accent)" }}>Local UI</span>
          <span
            style={{
              background: "rgba(34, 197, 94, 0.15)",
              color: "var(--green)",
              fontSize: "10px",
              fontWeight: 600,
              padding: "2px 8px",
              borderRadius: "4px",
              letterSpacing: "0.5px",
            }}
          >
            127.0.0.1
          </span>
        </div>

        <nav className="nav-bar">
          {navLinks.map((link) => {
            const isActive = link.match(location.pathname);
            return (
              <Link
                key={link.to}
                to={link.to}
                className={`nav-link ${isActive ? "active" : ""}`}
              >
                {link.label}
                {isActive && (
                  <motion.div
                    className="nav-indicator"
                    layoutId="nav-indicator"
                    style={{ position: "absolute", bottom: -1, left: 8, right: 8, height: 2 }}
                    transition={{ type: "spring", stiffness: 380, damping: 30 }}
                  />
                )}
              </Link>
            );
          })}
        </nav>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "12px",
            color: "var(--text-dim)",
          }}
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5" aria-hidden="true">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
          Encrypted locally
        </div>
      </header>

      <main style={{ padding: "32px 24px", maxWidth: 1200, margin: "0 auto" }}>
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            variants={pageVariants}
            initial="initial"
            animate="enter"
            exit="exit"
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
