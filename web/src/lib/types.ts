export type NamespaceInfo = {
  namespace: string;
  documents: number;
  chunks: number;
};

export type CourseRequest = {
  goal: string;
  namespace?: string | null;
  user?: string | null;
  use_style?: boolean;
  limit?: number;
  skip_ingest?: boolean;
  with_quiz?: boolean;
};

export type CourseProgress = {
  /** Indices of sections the reader has marked as read. */
  modules_read?: number[];
  /** Where they stopped, so reopening lands in the right place. */
  bookmark?: { module_index: number; anchor?: string } | null;
};

export type SavedCourseSummary = {
  id: number;
  user_id: string;
  goal: string;
  summary: string;
  namespace: string;
  module_titles: string[];
  module_count: number;
  estimated_cost_usd: number | null;
  with_quiz: boolean;
  used_style: boolean;
  created_at: string;
  progress?: CourseProgress;
  opened_at?: string | null;
};

export type SavedModule = {
  index: number;
  title: string;
  notes: ModuleNotes | null;
  error: string | null;
};

export type SavedCourse = SavedCourseSummary & {
  modules: SavedModule[];
};

export type Chunk = {
  id: number;
  text: string;
  document_title: string;
  document_url: string | null;
  score: number;
};

export type QuizQuestion = {
  question: string;
  options: string[];
  answer_index: number;
  explanation: string;
};

export type Quiz = {
  questions: QuizQuestion[];
};

export type ModuleNotes = {
  module_title: string;
  body: string;
  cited_chunk_ids: number[];
  chunks: Chunk[];
  refused: boolean;
  refusal_reason: string | null;
  quiz: Quiz | null;
};

export type StyleProfile = {
  sentence_length: "short" | "medium" | "long" | "varied";
  structure: "prose" | "bullets" | "mixed";
  formality: "casual" | "neutral" | "formal";
  person: "first" | "second" | "third" | "impersonal";
  vocabulary: "plain" | "mixed" | "technical";
  uses_analogies: boolean;
  uses_worked_examples: boolean;
  uses_notation: boolean;
  signature_habits: string[];
  summary: string;
};

export type UsageEntry = {
  model: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
};

export type CourseEvent =
  | { type: "planning" }
  | {
      type: "syllabus";
      summary: string;
      namespace: string;
      modules: string[];
    }
  | { type: "ingesting"; namespace: string }
  | { type: "ingested"; cached: boolean; chunks: number }
  | { type: "module_start"; index: number; title: string }
  | { type: "token"; index: number; text: string }
  | { type: "module"; index: number; notes: ModuleNotes }
  | { type: "module_error"; index: number; error: string }
  | {
      type: "done";
      estimated_cost_usd: number;
      usage: UsageEntry[];
    }
  | { type: "saved"; id: number }
  | { type: "error"; error: string };

export type ModuleState = {
  index: number;
  title: string;
  streamingText: string;
  notes: ModuleNotes | null;
  error: string | null;
  status: "pending" | "streaming" | "done" | "refused" | "error";
};

export type UploadResult = {
  namespace: string;
  documents?: number;
  chunks?: number;
  [key: string]: unknown;
};
