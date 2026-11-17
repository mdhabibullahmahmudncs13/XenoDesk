import { notFound } from "next/navigation";
import { AuthForm } from "../../components/AuthForm";
import { Chat } from "../../components/Chat";
import { CustomerHistory } from "../../components/CustomerHistory";
import { Screen } from "../../components/Screen";
import { SignupForm } from "../../components/SignupForm";
import { Tour } from "../../components/Tour";

const screens: Record<string, { title: string; endpoint?: string; blocked?: boolean }> = {
  login: { title: "Sign in" },
  signup: { title: "Sign up" },
  "auth/login": { title: "Sign in" },
  "auth/signup": { title: "Sign up" },
  dashboard: { title: "Dashboard", endpoint: "/api/v1/notifications?limit=1", },
  "customer-genome/history": { title: "Customer history", blocked: true },
  "customer-genome/restore-product": { title: "Restore product", endpoint: "/api/v1/customer-genome/product-interests" },
  "customer-genome/waiting-lists": { title: "Waiting lists", endpoint: "/api/v1/customer-genome/product-interests" },
  "customer-genome/restock-events": { title: "Restock events", blocked: true },
  "customer-genome/batch-preview": { title: "Batch preview", blocked: true },
  "customer-genome/repeat-buyers": {
    title: "Repeat buyers",
    endpoint: "/api/v1/customer-genome/repeat-buyers",
  },
  "customer-genome/product-interests": {
    title: "Restore product",
    endpoint: "/api/v1/customer-genome/product-interests",
  },
  "creator-commerce/reviews": {
    title: "Reviews",
    endpoint: "/api/v1/creator-commerce/reviews/library",
  },
  "creator-commerce/reviews/detail": {
    title: "Review detail",
    endpoint: "/api/v1/creator-commerce/reviews/library",
  },
  "creator-commerce/reviews/settings": {
    title: "Review settings",
    endpoint: "/api/v1/creator-commerce/reviews/settings",
  },
  "creator-commerce/reviews/export": {
    title: "Review export",
    endpoint: "/api/v1/creator-commerce/reviews/export",
  },
  "creator-commerce/reviews/cards": {
    title: "Marketing cards",
    endpoint: "/api/v1/creator-commerce/reviews/library",
  },
  "creator-commerce/ads": {
    title: "Ads intelligence",
    blocked: true,
  },
  "creator-commerce/ads/insights": { title: "Ads insights", blocked: true },
  "creator-commerce/ads/own": {
    title: "My ads performance",
    blocked: true,
  },
  "creator-commerce/ads/performance": { title: "My ads performance", blocked: true },
  "creator-commerce/collaborations": {
    title: "Collaboration finder",
    blocked: true,
  },
  "creator-commerce/influencers": {
    title: "Influencer suggestions",
    blocked: true,
  },
  "creator-commerce/collaborations/influencers": { title: "Influencer suggestions", blocked: true },
  "agent-workspace": {
    title: "Agent workspace",
    endpoint: "/api/v1/agent-workspace/faqs",
  },
  "agent-workspace/faqs": {
    title: "FAQ management",
    endpoint: "/api/v1/agent-workspace/faqs",
  },
  "agent-workspace/tours": {
    title: "Tour management",
    endpoint: "/api/v1/agent-workspace/tours/steps",
  },
  "workspace/chat": { title: "Chat" },
  "workspace/faqs": { title: "FAQ management", endpoint: "/api/v1/agent-workspace/faqs" },
  "workspace/tour": { title: "Tour management", endpoint: "/api/v1/agent-workspace/tours/steps" },
  "notifications": {
    title: "Notifications",
    endpoint: "/api/v1/notifications",
  },
  settings: { title: "Settings", endpoint: "/api/v1/creator-commerce/reviews/settings" },
  "settings/account": { title: "Account settings", endpoint: "/api/v1/auth/me" },
  chat: { title: "Chat", endpoint: "/api/v1/agent-workspace/faqs" },
  "customer-genome": { title: "Customer genome", blocked: true },
  "creator-commerce": { title: "Creator commerce", blocked: true },
  tour: { title: "Product tour", endpoint: "/api/v1/agent-workspace/tours/steps" },
};

export default async function RoutedScreen({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}) {
  const { slug } = await params;
  const key = slug.join("/");
  let screen = screens[key];
  if (!screen && key.startsWith("customer-genome/restock-events/") && key.endsWith("/preview")) {
    const eventId = key.split("/")[2];
    screen = { title: "Batch preview and confirm", endpoint: `/api/v1/customer-genome/restocks/${eventId}/preview` };
  }
  if (!screen && key.startsWith("creator-commerce/reviews/") && key.split("/").length === 3) {
    const reviewId = key.split("/")[2];
    screen = { title: "Review detail", endpoint: `/api/v1/creator-commerce/reviews/${reviewId}` };
  }
  if (!screen) notFound();
  if (key === "login" || key === "auth/login") return <AuthForm />;
  if (key === "signup" || key === "auth/signup") return <SignupForm />;
  if (key === "chat" || key === "workspace/chat") return <Chat />;
  if (key === "tour" || key === "workspace/tour") return <Tour />;
  if (key === "customer-genome/history") return <CustomerHistory />;
  return (
    <Screen
      title={screen.title}
      description="Live data from the Xenovarients API."
      endpoint={screen.endpoint}
      blocked={screen.blocked}
      list={Boolean(screen.endpoint)}
    />
  );
}
