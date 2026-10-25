import { BuyerAppShell } from "@/components/BuyerAppShell";
import { BuyerGate } from "@/components/BuyerGate";

export default function BuyerLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <BuyerGate>
      <BuyerAppShell>{children}</BuyerAppShell>
    </BuyerGate>
  );
}
