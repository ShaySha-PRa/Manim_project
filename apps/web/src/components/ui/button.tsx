import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "quiet";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  readonly variant?: ButtonVariant;
  readonly fullWidth?: boolean;
};

export function Button({
  className = "",
  fullWidth = false,
  type = "button",
  variant = "primary",
  ...props
}: Readonly<ButtonProps>) {
  const widthClassName = fullWidth ? " ui-button--full" : "";
  return (
    <button
      className={`ui-button ui-button--${variant}${widthClassName} ${className}`.trim()}
      type={type}
      {...props}
    />
  );
}
