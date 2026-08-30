import type { ReactNode, ButtonHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react';
import { ArrowRight } from 'lucide-react';

// ── Roman numerals ──────────────────────────────────────────────────────────
const ROMAN: [number, string][] = [
  [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'],
  [100, 'C'], [90, 'XC'], [50, 'L'], [40, 'XL'],
  [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
];
export function toRoman(n: number): string {
  let num = n;
  let out = '';
  for (const [val, sym] of ROMAN) {
    while (num >= val) {
      out += sym;
      num -= val;
    }
  }
  return out;
}
export const pad2 = (n: number) => String(n).padStart(2, '0');

// ── Section label — "§ 01 — TITLE" ──────────────────────────────────────────
export function SectionLabel({ index, title, trailing }: { index: number; title: string; trailing?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-4">
      <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-rust">
        § {pad2(index)} — {title}
      </p>
      {trailing && <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-charcoal">{trailing}</div>}
    </div>
  );
}

// ── Panel — bordered container, sharp corners ───────────────────────────────
export function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`border border-hairline bg-parchment-2/60 ${className}`}>{children}</div>;
}

// ── Crosshair — architectural "+" marker for grid-lattice corners ───────────
export function Crosshair({ className = '' }: { className?: string }) {
  return <span aria-hidden className={`pointer-events-none select-none font-mono text-xs leading-none text-rust ${className}`}>+</span>;
}

// ── LatticeFrame — wraps a border-collapsed grid with corner crosshairs ─────
export function LatticeFrame({ children, className = '' }: { children: ReactNode; className?: string }) {
  const pos = 'absolute z-10';
  return (
    <div className={`relative ${className}`}>
      <Crosshair className={`${pos} -top-[7px] -left-[7px]`} />
      <Crosshair className={`${pos} -top-[7px] -right-[7px]`} />
      <Crosshair className={`${pos} -bottom-[7px] -left-[7px]`} />
      <Crosshair className={`${pos} -bottom-[7px] -right-[7px]`} />
      {children}
    </div>
  );
}

// ── MetricCard — inset architectural specimen card (§ 01 / § 05 style) ──────
export function MetricCard({
  index,
  label,
  value,
  unit,
  footnote,
  className = '',
}: {
  index: number;
  label: string;
  value: ReactNode;
  unit?: string;
  footnote?: string;
  className?: string;
}) {
  return (
    <div className={`bg-parchment-3 p-5 flex flex-col justify-between ${className}`}>
      <div className="flex items-start justify-between gap-3 font-mono text-[10px] uppercase tracking-widest">
        <span className="text-rust font-bold">{toRoman(index)}. {label}</span>
        {unit && <span className="text-charcoal opacity-75 shrink-0">{unit}</span>}
      </div>
      <p className="font-serif tracking-tight text-3xl md:text-4xl font-semibold text-ink tabular-nums my-3">{value}</p>
      {footnote && (
        <p className="pt-2 border-t border-hairline-2 font-mono text-[10px] text-charcoal uppercase tracking-wider">
          {footnote}
        </p>
      )}
    </div>
  );
}

// ── EmptyState — scientific "awaiting telemetry" placeholder ────────────────
export function EmptyState({
  message = 'Awaiting Telemetry · Pipeline Idle',
  className = '',
}: {
  message?: string;
  className?: string;
}) {
  return (
    <div
      className={`h-full min-h-[120px] flex items-center justify-center bg-[radial-gradient(#dcd4c4_1px,transparent_1px)] [background-size:16px_16px] ${className}`}
    >
      <span className="font-mono text-[11px] tracking-widest text-charcoal uppercase bg-parchment border border-hairline px-3 py-1.5">
        [ {message} ]
      </span>
    </div>
  );
}

// ── ChartStatusPill — "● 200MS TARGET BUDGET" style header badge ────────────
export function ChartStatusPill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-rust">
      <span aria-hidden>●</span>{children}
    </span>
  );
}

// ── Button ───────────────────────────────────────────────────────────────────
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export function Button({
  children,
  variant = 'primary',
  arrow = true,
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; arrow?: boolean }) {
  const base = 'inline-flex items-center justify-center gap-2 font-mono text-xs font-semibold uppercase tracking-[0.15em] px-5 py-3 border transition-colors active:translate-y-px disabled:opacity-40 disabled:cursor-not-allowed disabled:active:translate-y-0';
  const variants: Record<ButtonVariant, string> = {
    primary: 'bg-ink text-parchment border-ink hover:bg-rust hover:border-rust active:bg-sienna active:border-sienna',
    secondary: 'bg-transparent text-ink border-ink hover:bg-ink hover:text-parchment active:bg-rust active:border-rust active:text-parchment',
    ghost: 'bg-transparent text-charcoal border-hairline hover:border-ink hover:text-ink active:bg-hairline/40',
    danger: 'bg-transparent text-sienna border-sienna/40 hover:bg-sienna hover:text-parchment active:bg-sienna/80',
  };
  return (
    <button className={`${base} ${variants[variant]} ${className}`} {...rest}>
      {children}
      {arrow && <ArrowRight size={13} strokeWidth={2.5} />}
    </button>
  );
}

// ── Field wrapper (label + control) ─────────────────────────────────────────
export function FieldLabel({ children }: { children: ReactNode }) {
  return <label className="block font-mono text-[10px] uppercase tracking-[0.2em] text-charcoal mb-2">{children}</label>;
}

export function Select({ className = '', ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select
        className={`w-full appearance-none bg-parchment border border-hairline px-3 py-2.5 pr-8 text-xs uppercase tracking-wider text-ink focus:outline-none focus:border-ink transition-colors font-mono cursor-pointer ${className}`}
        {...rest}
      />
      <span aria-hidden className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-xs text-rust">▾</span>
    </div>
  );
}

export function TextArea({ className = '', ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`w-full bg-transparent border border-hairline px-4 py-4 text-sm text-ink focus:outline-none focus:border-ink transition-colors resize-none ${className}`}
      {...rest}
    />
  );
}

// ── Status badge — decision states ──────────────────────────────────────────
export const DECISION_COLORS: Record<string, string> = {
  ALLOW: 'text-forest border-forest/40',
  SANITIZE: 'text-charcoal border-charcoal/40',
  REVIEW: 'text-rust border-rust/40',
  BLOCK: 'text-sienna border-sienna/40',
};
export const DECISION_HEX: Record<string, string> = {
  ALLOW: '#3f5b44',
  SANITIZE: '#54524d',
  REVIEW: '#b84318',
  BLOCK: '#8c2f12',
};
export function StatusBadge({ decision, size = 'sm' }: { decision: string; size?: 'sm' | 'md' }) {
  const cfg = DECISION_COLORS[decision] ?? 'text-charcoal border-hairline';
  const sizeCls = size === 'md' ? 'text-xs px-3 py-1' : 'text-[10px] px-2 py-0.5';
  return (
    <span className={`font-mono font-semibold uppercase tracking-widest border ${cfg} ${sizeCls}`}>
      {decision}
    </span>
  );
}

// ── Index row number — "01", "02" ───────────────────────────────────────────
export function IndexNo({ n }: { n: number }) {
  return <span className="font-mono text-[11px] text-charcoal/70 tabular-nums">{pad2(n)}</span>;
}

// ── Utility bar — header/footer microcopy strip ─────────────────────────────
export function UtilityBar({ left, right }: { left?: ReactNode; right: ReactNode }) {
  return (
    <div className="border-hairline flex items-center justify-between px-6 py-2 font-mono text-[10px] uppercase tracking-[0.2em] text-charcoal">
      <span>{left}</span>
      <span>{right}</span>
    </div>
  );
}
