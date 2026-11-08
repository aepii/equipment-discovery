import { ArrowUp } from "lucide-react";
import { useEffect, useId, useRef } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  compare: boolean;
  onCompareChange: (value: boolean) => void;
  busy: boolean;
  label: string;
  placeholder?: string;
  autoFocus?: boolean;
}

export function Composer({ value, onChange, onSubmit, compare, onCompareChange, busy, label, placeholder, autoFocus }: Props) {
  const id = useId();
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);
  const empty = !value.trim();
  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (!empty && !busy) onSubmit();
      }}
    >
      <label htmlFor={id} className="composer__label">
        {label}
      </label>
      <textarea
        id={id}
        ref={ref}
        rows={2}
        value={value}
        maxLength={2000}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (!empty && !busy) onSubmit();
          }
        }}
      />
      <div className="composer__row">
        <label className="check">
          <input type="checkbox" checked={compare} onChange={(event) => onCompareChange(event.target.checked)} />
          <span>Compare with general AI</span>
        </label>
        <button type="submit" className="button button--primary" disabled={empty || busy}>
          Ask
          <ArrowUp size={18} aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
