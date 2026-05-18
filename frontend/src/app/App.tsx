import { ExtractionPage } from "@/pages/extraction";
import { ErrorBoundary } from "./ErrorBoundary";
import "./App.css";

export default function App() {
  return (
    <ErrorBoundary>
      <ExtractionPage />
    </ErrorBoundary>
  );
}
