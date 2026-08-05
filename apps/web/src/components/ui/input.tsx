import type { InputHTMLAttributes } from "react";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export function Input({ className = "", ...props }: Readonly<InputProps>) {
  return <input className={`ui-input ${className}`.trim()} {...props} />;
}
