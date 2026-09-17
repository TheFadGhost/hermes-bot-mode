import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

type DisclosureProps = {
  accountId?: string;
  section: string;
  id: string;
  label?: string;
  children: ReactNode;
  className?: string;
};

function disclosureKey(accountId: string | undefined, section: string, id: string): string {
  return `hermes-disclosure:${accountId || "account"}:${section}:${id}`;
}

function readStored(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "open";
  } catch {
    return false;
  }
}

export function Disclosure({ accountId, section, id, label = "Details", children, className }: DisclosureProps): JSX.Element {
  const storageKey = useMemo(() => disclosureKey(accountId, section, id), [accountId, id, section]);
  const controlId = useMemo(() => `disclosure-${storageKey.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "")}`, [storageKey]);
  const [open, setOpen] = useState(() => readStored(storageKey));

  useEffect(() => setOpen(readStored(storageKey)), [storageKey]);

  const toggle = () => {
    setOpen((current) => {
      const next = !current;
      try {
        window.localStorage.setItem(storageKey, next ? "open" : "closed");
      } catch {
        // A storage failure must not make the disclosure unusable.
      }
      return next;
    });
  };

  return <div className={`hermes-disclosure ${className ?? ""}`.trim()}>
    <button className="hermes-disclosure-toggle" type="button" aria-expanded={open} aria-controls={controlId} onClick={toggle}>
      <span>{open ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}</span><ChevronDown size={14} aria-hidden="true" />
    </button>
    {open ? <div className="hermes-disclosure-content" id={controlId}>{children}</div> : null}
  </div>;
}

