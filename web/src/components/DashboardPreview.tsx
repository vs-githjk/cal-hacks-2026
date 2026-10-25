"use client";
// web/src/components/DashboardPreview.tsx
// The buyer dashboard in miniature, on the landing (#448): what each tile will show once the buyer has a goal. No numbers
// and no sample deal here (Vidyut): the real values appear on /buyer after sign-up.
import { SHIELD } from "@/lib/brand";
import { StatusPill } from "./ui";

export function DashboardPreview() {
  return (
    <div className="fm-glass overflow-hidden rounded-[22px] p-0" role="img" aria-label="The buyer dashboard: your goal, the sealed round, the approval code and the receipt">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <span className="flex items-center gap-2 text-[13px] font-medium text-ink-2">
          <span className="flex gap-1.5" aria-hidden><i className="h-2.5 w-2.5 rounded-full bg-coral-mark/70" /><i className="h-2.5 w-2.5 rounded-full bg-amber/60" /><i className="h-2.5 w-2.5 rounded-full bg-mint-mark/70" /></span>
          Your dashboard
        </span>
        <span className="text-[12px] text-muted">Fills in once you set a goal</span>
      </div>
      <div className="grid gap-3 p-4 md:grid-cols-4 md:p-5">
        <Mini label="Goal" pill={<StatusPill tone="live" pulse>Hunting</StatusPill>}>
          <p className="text-[17px] font-semibold leading-[22px]">What you are after</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">The part, your price cap and your date. Your agent hunts under the cap.</p>
        </Mini>
        <Mini label="Round" pill={<StatusPill tone="sealed">Sealed</StatusPill>}>
          <p className="text-[17px] font-semibold leading-[22px]">Who is bidding</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">Seller agents bid blind. {SHIELD} screens each listing, then the referee ranks them.</p>
        </Mini>
        <Mini label="Approve" pill={<StatusPill tone="live" pulse>Calling</StatusPill>}>
          <p className="text-[17px] font-semibold leading-[22px]">Your spoken code</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">Above your allowance we call you. The one-time code shows here, nowhere else.</p>
        </Mini>
        <Mini label="Receipt" pill={<StatusPill tone="good">Paid</StatusPill>}>
          <p className="text-[17px] font-semibold leading-[22px]">One per part</p>
          <p className="mt-1 text-[13px] leading-[18px] text-ink-2">The signed mandate and the charge, in Stripe test mode.</p>
        </Mini>
      </div>
    </div>
  );
}

function Mini({ label, pill, children }: { label: string; pill: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="fm-tile rounded-2xl p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium uppercase tracking-[0.04em] text-muted">{label}</span>
        {pill}
      </div>
      {children}
    </div>
  );
}
