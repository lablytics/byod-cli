import { motion } from "framer-motion";
import { pulseVariants } from "../animations/variants";

export function SecurityBanner() {
  return (
    <div
      className="security-notice"
      style={{ borderLeft: "3px solid rgba(34, 197, 94, 0.4)" }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
        <motion.svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--green)"
          strokeWidth="2"
          variants={pulseVariants}
          animate="animate"
          aria-hidden="true"
        >
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          <path d="M9 12l2 2 4-4" />
        </motion.svg>
        <strong>Zero-knowledge encryption</strong>
      </div>
      <span style={{ color: "var(--text-dim)" }}>
        Your data is encrypted on this machine using your AWS KMS key before upload.
        Neither Lablytics nor anyone else can access your plaintext data. Only the
        cryptographically attested Nitro Enclave can decrypt it for processing.
      </span>
    </div>
  );
}
