import { redirect } from "next/navigation";

/** /seller on its own opens the seller screen the nav links to (#398: never a 404). */
export default function SellerIndex() {
  redirect("/seller/seller-a");
}
