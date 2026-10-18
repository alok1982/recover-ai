/** RecoverAI brand: the approved RAI tile + "RecoverAI" wordmark (outlined SVGs in /public/brand, no font dependency). */
export function Logo({ variant = "full", tone = "light", height = 32, className = "" }: {
  variant?: "full" | "mark"; tone?: "light" | "dark"; height?: number; className?: string;
}) {
  const src = variant === "mark" ? "/brand/rai_mark.svg" : tone === "dark" ? "/brand/rai_logo_dark.svg" : "/brand/rai_logo.svg";
  const width = Math.round(variant === "mark" ? height : (height * 470) / 120);
  return <img className={`logo ${variant} ${className}`.trim()} src={src} alt="RecoverAI" width={width} height={height} data-testid="brand-logo" />;
}
