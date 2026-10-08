type Props = {
  tone?: "white" | "color";
  className?: string;
};

export function BrandMark({ tone = "white", className }: Props) {
  const src =
    tone === "color"
      ? "/brand/ohush-horizontal-color.svg"
      : "/brand/ohush-horizontal-white.svg";
  return (
    <img
      className={["brand", tone === "color" ? "brand-color" : "", className].filter(Boolean).join(" ")}
      src={src}
      alt="OHush"
    />
  );
}
