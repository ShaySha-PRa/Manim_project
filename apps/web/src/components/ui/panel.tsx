import type { HTMLAttributes } from "react";

type PanelProps = HTMLAttributes<HTMLElement> & {
  readonly as?: "article" | "section" | "div";
};

export function Panel({
  as: Component = "section",
  className = "",
  ...props
}: Readonly<PanelProps>) {
  return <Component className={`ui-panel ${className}`.trim()} {...props} />;
}
