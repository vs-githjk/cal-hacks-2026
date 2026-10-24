// 21st.dev DotPattern (Magic UI), adapted: typed props, no fixed inner id, Ledger token fill. Decorative only; never carries data.
import { useId, type SVGProps } from "react";
import { cn } from "@/lib/utils";

type Len = number | string;

interface DotPatternProps extends Omit<SVGProps<SVGSVGElement>, "width" | "height" | "x" | "y"> {
  width?: Len;
  height?: Len;
  x?: Len;
  y?: Len;
  cx?: Len;
  cy?: Len;
  cr?: Len;
  className?: string;
}

function DotPattern({ width = 16, height = 16, x = 0, y = 0, cx = 1, cy = 1, cr = 1, className, ...props }: DotPatternProps) {
  const id = useId();
  return (
    <svg aria-hidden="true" className={cn("pointer-events-none absolute inset-0 h-full w-full fill-muted/40", className)} {...props}>
      <defs>
        <pattern id={id} width={width} height={height} patternUnits="userSpaceOnUse" patternContentUnits="userSpaceOnUse" x={x} y={y}>
          <circle cx={cx} cy={cy} r={cr} />
        </pattern>
      </defs>
      <rect width="100%" height="100%" strokeWidth={0} fill={`url(#${id})`} />
    </svg>
  );
}

export { DotPattern };
