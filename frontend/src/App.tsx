import { Route, Routes } from "react-router-dom";
import { Compare } from "./pages/Compare";
import { Method, NotFound, Privacy, Terms } from "./pages/Docs";
import { Home } from "./pages/Home";
import { Profile } from "./pages/Profile";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/u/:qid" element={<Profile />} />
      <Route path="/compare" element={<Compare />} />
      <Route path="/method" element={<Method />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
