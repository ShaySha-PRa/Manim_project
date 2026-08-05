import type { HTMLAttributes } from "react";

type StatusTone = "error" | "info" | "success";

type StatusMessageProps = HTMLAttributes<HTMLParagraphElement> & {
  readonly tone?: StatusTone;
};

export function StatusMessage({
  className = "",
  tone = "info",
  ...props
}: Readonly<StatusMessageProps>) {
  return (
    <p
      aria-live={tone === "error" ? "assertive" : "polite"}
      className={`ui-status ui-status--${tone} ${className}`.trim()}
      role={tone === "error" ? "alert" : "status"}
      {...props}
    />
  );
}
