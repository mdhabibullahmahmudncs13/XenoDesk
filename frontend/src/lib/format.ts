/** Display helpers shared by the Customer Genome screens. */

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unavailable";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatMoney(amount: string | number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === "") return "Unavailable";
  const value = typeof amount === "number" ? amount : Number(amount);
  if (Number.isNaN(value)) return "Unavailable";
  return `${currency} ${value.toLocaleString("en-GB", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function contactOf(customer: {
  phone_e164?: string | null;
  email_normalised?: string | null;
}): string | null {
  return customer.phone_e164 ?? customer.email_normalised ?? null;
}
