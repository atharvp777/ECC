import { useId } from "react";

/**
 * OrbitInput — labeled text input primitive.
 *
 * Supports optional label, helper text and error state.
 * Error wins over helper when both are provided.
 */
export default function OrbitInput({
  label,
  helper,
  error,
  id: idProp,
  className = "",
  ...rest
}) {
  const autoId = useId();
  const id = idProp || autoId;
  const errorId = `${id}-error`;
  const helperId = `${id}-helper`;

  const describedBy =
    [error ? errorId : null, helper && !error ? helperId : null]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <div className="orbit-field">
      {label && (
        <label className="orbit-field__label" htmlFor={id}>
          {label}
        </label>
      )}
      <input
        id={id}
        className={["orbit-input", error ? "orbit-input--error" : "", className]
          .filter(Boolean)
          .join(" ")}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...rest}
      />
      {error && (
        <span className="orbit-field__error" id={errorId} role="alert">
          {error}
        </span>
      )}
      {helper && !error && (
        <span className="orbit-field__helper" id={helperId}>
          {helper}
        </span>
      )}
    </div>
  );
}