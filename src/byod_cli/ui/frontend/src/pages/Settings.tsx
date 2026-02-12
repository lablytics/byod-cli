import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { staggerContainer, staggerItem, fadeInUp } from "../animations/variants";
import { apiFetch } from "../hooks/useApi";

interface Profile {
  name: string;
  active: boolean;
  api_url: string;
  has_api_key: boolean;
  settings: Record<string, string>;
}

interface ConfigInfo {
  config_path: string;
  active_profile: string | null;
  api_url: string;
  api_key_set: boolean;
}

export function Settings() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [config, setConfig] = useState<ConfigInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch<Profile[]>("/settings/profiles"),
      apiFetch<ConfigInfo>("/settings/config"),
    ])
      .then(([p, c]) => {
        setProfiles(p);
        setConfig(c);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const activateProfile = async (name: string) => {
    await apiFetch(`/settings/profiles/${name}/activate`, { method: "POST" });
    setProfiles((ps) =>
      ps.map((p) => ({ ...p, active: p.name === name }))
    );
  };

  if (loading) return <div className="loading">Loading settings...</div>;

  return (
    <motion.div variants={fadeInUp} initial="initial" animate="animate">
      <div className="page-header">
        <h1>Settings</h1>
        <p>Manage profiles and view configuration</p>
      </div>

      {/* Config overview */}
      {config && (
        <div className="card" style={{ marginBottom: "24px" }}>
          <h3 style={{ fontSize: "16px", marginBottom: "16px" }}>Configuration</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px" }}>
            <div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" }}>
                Config File
              </div>
              <div style={{ fontFamily: "monospace", fontSize: "13px" }}>{config.config_path}</div>
            </div>
            <div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" }}>
                API URL
              </div>
              <div style={{ fontFamily: "monospace", fontSize: "13px" }}>{config.api_url}</div>
            </div>
            <div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" }}>
                Active Profile
              </div>
              <div style={{ fontSize: "14px" }}>{config.active_profile || "None"}</div>
            </div>
            <div>
              <div style={{ fontSize: "12px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "4px" }}>
                API Key
              </div>
              <div style={{ fontSize: "14px", color: config.api_key_set ? "var(--green)" : "var(--red)" }}>
                {config.api_key_set ? "Configured" : "Not set"}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Profiles */}
      <h3 style={{ fontSize: "16px", marginBottom: "16px" }}>Profiles</h3>
      {profiles.length === 0 ? (
        <div className="card" style={{ textAlign: "center", padding: "48px" }}>
          <p style={{ color: "var(--text-dim)", marginBottom: "12px" }}>No profiles configured</p>
          <div className="cli-hint">byod auth login</div>
        </div>
      ) : (
        <motion.div
          style={{ display: "flex", flexDirection: "column", gap: "12px" }}
          variants={staggerContainer}
          initial="initial"
          animate="animate"
        >
          {profiles.map((profile) => (
            <motion.div
              key={profile.name}
              className="card"
              variants={staggerItem}
              style={{
                borderColor: profile.active ? "var(--accent)" : undefined,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
                  <span style={{ fontWeight: 600, fontSize: "16px" }}>{profile.name}</span>
                  {profile.active && (
                    <span className="badge badge-completed">Active</span>
                  )}
                </div>
                <div style={{ fontSize: "13px", color: "var(--text-dim)" }}>
                  {profile.api_url}
                  {profile.has_api_key && " \u2022 API key set"}
                </div>
                {Object.keys(profile.settings).length > 0 && (
                  <div style={{ marginTop: "8px", fontSize: "12px", color: "var(--text-dim)" }}>
                    {Object.entries(profile.settings).map(([k, v]) => (
                      <div key={k}>
                        <span style={{ color: "var(--text)" }}>{k}:</span>{" "}
                        <span style={{ fontFamily: "monospace" }}>
                          {v.length > 40 ? v.slice(0, 20) + "..." + v.slice(-12) : v}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              {!profile.active && (
                <button className="btn-small" onClick={() => activateProfile(profile.name)}>
                  Activate
                </button>
              )}
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* CLI reference */}
      <div style={{ marginTop: "32px" }}>
        <h3 style={{ fontSize: "16px", marginBottom: "12px" }}>CLI Commands</h3>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div className="cli-hint">byod profile list</div>
          <div className="cli-hint">byod profile switch &lt;name&gt;</div>
          <div className="cli-hint">byod auth login</div>
        </div>
      </div>
    </motion.div>
  );
}
