const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, BorderStyle, PageBreak } = require("docx");
const fs = require("fs");
const path = require("path");

function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 160, before: opts.before ?? 0, line: 276 },
    ...opts.para,
    children: [
      new TextRun({
        text,
        font: "Calibri",
        size: opts.size ?? 22,
        bold: opts.bold ?? false,
        italics: opts.italics ?? false,
        color: opts.color,
      }),
    ],
  });
}

function multi(parts, opts = {}) {
  return new Paragraph({
    spacing: { after: opts.after ?? 160, before: opts.before ?? 0, line: 276 },
    children: parts.map(
      (part) =>
        new TextRun({
          text: part.text,
          font: "Calibri",
          size: opts.size ?? 22,
          bold: part.bold ?? false,
          italics: part.italics ?? false,
        })
    ),
  });
}

function slideTitle(n, title) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 200, after: 200 },
    border: {
      bottom: { style: BorderStyle.SINGLE, size: 12, color: "1F4E79", space: 8 },
    },
    children: [
      new TextRun({
        text: `Slide ${n} — ${title}`,
        font: "Calibri",
        size: 32,
        bold: true,
        color: "1F4E79",
      }),
    ],
  });
}

function label(text) {
  return p(text, { bold: true, size: 24, after: 80, before: 120, color: "2E75B6" });
}

function say(text) {
  return p(text, { size: 22, after: 140 });
}

function tip(text) {
  return p("Tip: " + text, { italics: true, size: 20, after: 120, color: "595959" });
}

function ifAsked(text) {
  return p("If asked: " + text, { size: 20, after: 120, color: "C65911" });
}

const slides = [
  {
    n: 1,
    title: "Title Slide",
    onSlide: "ASKa-Piyu title, full study name, researchers, GitHub, LSPU CCS, date.",
    say: [
      "Good morning / good afternoon, panelists.",
      "We are John Christian Coronacion and Wilmark Veridiano from the College of Computer Studies, LSPU Santa Cruz.",
      "Our study is ASKa-Piyu: A Knowledge Base and Technical Support System with Smart Ticket Routing and Prioritization for University Services in Laguna State Polytechnic University.",
      "In short, ASKa-Piyu helps students and faculty find official campus information and escalate unresolved concerns through tickets — with humans still in control.",
    ],
    tips: ["Smile, introduce yourselves clearly, then pause one second before Slide 2."],
    ifAsked: ["GitHub is our source repository for the prototype and documentation."],
  },
  {
    n: 2,
    title: "Why ASKa-Piyu? (Introduction & Background)",
    onSlide: "Scattered documents, repeated inquiries, manual routing → Semantic Retrieval, Citation-grounded RAG, Smart Ticketing.",
    say: [
      "University service information exists, but it is not always easy to find, understand, or act on.",
      "Documents are scattered across offices and files. Students often ask the same questions again and again. When something needs an office action, routing is still mostly manual.",
      "Also, users may describe a problem in everyday words, while official handbooks use formal terms — so keyword search alone is not enough.",
      "ASKa-Piyu connects three pieces: semantic retrieval to find the right passages, citation-grounded RAG so answers point back to sources, and smart ticketing when a human must take over.",
      "So we move from fragmented support to one bounded support workflow.",
    ],
    tips: ["Point to the left problems, then the right solutions as you speak."],
    ifAsked: [
      "Bounded means the system helps with authorized documents and tickets — it does not approve payments, release records, or make official decisions by itself.",
    ],
  },
  {
    n: 3,
    title: "Problem, Objectives, Scope & Limitations",
    onSlide: "Three columns: Research Problem, Objectives (1–6), Scope & Limitations.",
    say: [
      "Research problem: users struggle to find the right source, understand formal procedures, know which office handles the concern, and track unresolved issues. That leads to repeated inquiries, delays, and extra office load.",
      "Our objectives were to identify the concerns and documents, design the web architecture, implement document processing with semantic retrieval, RAG, and citation grounding, implement smart ticket routing and evaluation, build role-based interfaces, and evaluate functionality, usability, and acceptance.",
      "Scope: LSPU Santa Cruz, six authorized non-confidential documents, ticket priorities Low to Urgent, and statuses Open, In Progress, Resolved, Closed.",
      "Limitation we want clear for the panel: ASKa-Piyu does not do official approvals, payments, records release, or autonomous decisions. Sensitive data stays out. Humans remain responsible for interpretation and final action.",
    ],
    tips: ["Read objectives briefly — do not recite every word. Focus on problem → what we built → what we refuse to automate."],
    ifAsked: ["Six documents were screened and approved for the controlled corpus — not the entire university archive."],
  },
  {
    n: 4,
    title: "Related Concepts & Research Gap",
    onSlide: "KMS, RAG, Smart Ticket Prioritization + research gap statement.",
    say: [
      "We grounded the design on three ideas from literature.",
      "Knowledge Management: collect, organize, store, retrieve, share, and apply institutional knowledge.",
      "RAG: index documents, retrieve relevant context, generate an answer, and attach source metadata.",
      "Smart ticket prioritization: create a ticket, classify the concern, route to an office, detect urgency, and prioritize.",
      "Research gap: many studies treat knowledge bases, chatbots, or ticketing separately. ASKa-Piyu integrates them into one localized, document-grounded university workflow with human-in-the-loop escalation.",
    ],
    tips: ["Say the gap in one clean sentence — panels listen for this."],
    ifAsked: ["We cite works such as Selvi et al., Huang & Huang, and Faldesiani & Senen as conceptual anchors, then localize to LSPU."],
  },
  {
    n: 5,
    title: "Research Methodology",
    onSlide: "Developmental + Descriptive + Evaluative; RAD phases; KB preparation pipeline; locale/ethics/evaluation.",
    say: [
      "Our design is developmental, descriptive, and evaluative: we built the system, described how it works, and measured results.",
      "Locale: LSPU Santa Cruz, using six authorized institutional documents.",
      "Ethics: non-confidential sources only, controlled access, and human oversight.",
      "We followed Rapid Application Development — requirements planning, user design, construction, and cutover — so we could iterate with feedback.",
      "For the knowledge base we collect and screen documents, extract or OCR, clean and chunk, tag metadata, then embed and index for search.",
      "Evaluation covered functional and pipeline tests, expert review, and user acceptance.",
    ],
    tips: ["If time is short, emphasize RAD + KB pipeline + ethics in three sentences."],
    ifAsked: [
      "Chunking splits long handbooks into searchable passages. Embedding turns text into vectors so similar meaning can match even when wording differs.",
    ],
  },
  {
    n: 6,
    title: "Overall Flow of ASKa-Piyu",
    onSlide: "Architecture / overall system flow diagram.",
    say: [
      "This slide shows the overall flow of ASKa-Piyu.",
      "A user can browse the Knowledge Base or ask a question. The system retrieves relevant authorized passages, generates a grounded answer with citations when possible, and if the concern still needs office action, the user can escalate to a ticket.",
      "Tickets are routed to the responsible office with a priority level, and staff handle them with human judgment.",
      "So Ask is for information; Tickets are for action.",
    ],
    tips: ["Walk the diagram left-to-right with your finger or pointer. Keep this slide slow."],
    ifAsked: [
      "Production uses a Flutter web client, FastAPI backend, PostgreSQL for records, and a vector store for document chunks.",
    ],
  },
  {
    n: 7,
    title: "Demo — Landing, Knowledge Base, Ask Assistant",
    onSlide: "Landing page, KB browse, Ask Assistant; login needed for tickets and supporting citations in the presented workflow.",
    say: [
      "For the system demonstration, we start at the landing page — the public entry point.",
      "In the Knowledge Base, users browse topics and institutional procedures from the approved documents.",
      "In Ask Assistant, users ask questions and receive document-based information.",
      "Important: public users can explore information, but logged-in access is required for ticket submission and for viewing supporting citations in the workflow we present.",
      "So the system assists with information while authentication protects restricted actions.",
    ],
    tips: ["If you live-demo: open Landing → KB → Ask one short student question (for example TOR fee)."],
    ifAsked: [
      "Answers are grounded on retrieved passages. If evidence is weak, the system should not invent official policy.",
    ],
  },
  {
    n: 8,
    title: "Demo — Ticketing & Human Oversight",
    onSlide: "Ticket submission, My Tickets, Office Workspace; priority and status ladders.",
    say: [
      "When documents alone are not enough, the concern is referred — not autonomously resolved.",
      "The user describes the concern, creates a ticket, selects or routes to an office, and a priority is assigned: Low, Medium, High, or Urgent.",
      "In My Tickets, the user can see status and priority.",
      "In the office workspace, staff review and handle assigned tickets.",
      "Statuses move through Open, In Progress, Resolved, and Closed — with people making the official decisions.",
    ],
    tips: ["Stress human oversight twice here — panels care about this."],
    ifAsked: [
      "After resolve, staff may convert useful resolutions into Knowledge Base drafts for review before publish — still human-controlled.",
    ],
  },
  {
    n: 9,
    title: "Actual Research Documentation (Photos)",
    onSlide: "Photos of IT expert testing and user evaluation; 10 IT experts, 50 intended users.",
    say: [
      "These are representative photographs from our actual evaluation activities — not stock images.",
      "We conducted IT expert testing for black-box and technical evaluation with 10 IT experts.",
      "We also conducted user acceptance and usability evaluation with 50 intended users.",
      "This shows the study was evaluated with real respondents, not only unit tests in code.",
    ],
    tips: ["Keep this short. Photos support credibility; results come on the next slides."],
    ifAsked: ["Respondents were intended users of the campus support workflow under our evaluation protocol."],
  },
  {
    n: 10,
    title: "Actual Model / Pipeline Testing",
    onSlide: "Pytest 25 passed; chunking/embedding checks; retrieval and answer generation key results.",
    say: [
      "Besides surveys, we also tested the technical pipeline.",
      "For unit and integration tests, pytest completed 25 passed cases across 4 suites.",
      "Chunking and embedding checks passed: local E5 embeddings at 384 dimensions were finite and repeatable.",
      "For retrieval and answer generation checks, a relevant source was retrieved, a non-empty answer was generated, and no fallback response was triggered in that test path.",
      "Separately, in Model Evaluation we also review classification, retrieval Hit@K, and QA/citation quality on labeled sets — so we evaluate both engineering correctness and answer quality.",
    ],
    tips: [
      "If they ask you to show terminal output: the chunking/E5 PASS boxes are pipeline checks; Model Evaluation prints accuracy / Hit@K style scores.",
    ],
    ifAsked: [
      "We use pretrained embedding and language models in a RAG pipeline. We did not train a custom ML model from scratch. The reranker is rule-based.",
    ],
  },
  {
    n: 11,
    title: "Results & Discussion",
    onSlide: "11/11 black-box passed; 25 pytest; users 4.71/5; IT experts 4.73/5 (Excellent).",
    say: [
      "Here are the consolidated findings.",
      "All 11 black-box test cases passed under the tested conditions.",
      "Pytest: 25 cases across 4 suites, with one OCR-related warning noted.",
      "Intended users, n equals 50, gave an overall mean of 4.71 out of 5 — Excellent.",
      "IT experts, n equals 10, gave 4.73 out of 5 — also Excellent.",
      "So both technical tests and respondent perceptions support that the prototype is usable and acceptable for the controlled scope we defined.",
    ],
    tips: ["Read the four big numbers slowly. Do not overclaim beyond the sample."],
    ifAsked: [
      "Excellent refers to our instrument’s interpretation of the Likert means. Results apply to this prototype and corpus, not every campus process.",
    ],
  },
  {
    n: 12,
    title: "Conclusion, Recommendations & Future Work",
    onSlide: "Current conclusion, recommended next steps, welcome panel recommendations.",
    say: [
      "In conclusion, ASKa-Piyu was developed and deployed as a controlled prototype for institutional information support and smart ticketing.",
      "It integrates authorized-document processing, semantic retrieval, RAG with citation grounding, PostgreSQL records, role-based access, and human escalation.",
      "We achieved integrated information support over six approved documents, and favorable measured perceptions from black-box tests and Excellent ratings from users and IT experts.",
      "Recommended next steps: expand only with authorization — add current validated office documents and continue controlled testing — and preserve human oversight for interpretation, approvals, and resolution.",
      "We also welcome recommendations from the panel for further improvement of ASKa-Piyu.",
    ],
    tips: ["End by inviting panel recommendations — then stop talking and wait."],
    ifAsked: [
      "Future work could include more offices and documents, deeper ticket analytics, and continued evaluation — still with human-in-the-loop controls.",
    ],
  },
  {
    n: 13,
    title: "Thank You",
    onSlide: "Thank You; presenters’ names; CCS.",
    say: [
      "Thank you, panelists.",
      "We are John Christian Coronacion and Wilmark Veridiano.",
      "We are ready for your questions.",
    ],
    tips: ["Stand still, smile, and wait. Do not rush into answers before the question finishes."],
    ifAsked: ["Repeat the question briefly, then answer in 2–4 short sentences."],
  },
];

const children = [
  new Paragraph({
    heading: HeadingLevel.TITLE,
    spacing: { after: 120 },
    children: [
      new TextRun({
        text: "ASKa-Piyu Final Defense — Speaker Script",
        font: "Calibri",
        size: 40,
        bold: true,
        color: "1F4E79",
      }),
    ],
  }),
  p("Student-friendly what-to-say notes for each PowerPoint slide (ASKa-Piyu_FOD).", {
    size: 22,
    after: 80,
  }),
  p("Researchers: John Christian B. Coronacion & Wilmark S. Veridiano · LSPU Santa Cruz · CCS · 18 November 2026", {
    size: 20,
    after: 200,
    italics: true,
  }),
  label("How to use this document"),
  say("Before each slide, glance at On this slide. Then say the script out loud in your own words — do not read robotically. Use Tip for delivery. Use If asked only when the panel probes."),
  say("Suggested pacing: Slides 1–5 setup, 6–8 demo, 9–11 evidence, 12–13 close. Keep total talk tight so there is time for questions."),
];

for (const s of slides) {
  children.push(new Paragraph({ children: [new PageBreak()] }));
  children.push(slideTitle(s.n, s.title));
  children.push(label("On this slide"));
  children.push(say(s.onSlide));
  children.push(label("What you can say"));
  for (const line of s.say) children.push(say(line));
  children.push(label("Delivery tips"));
  for (const line of s.tips) children.push(tip(line));
  children.push(label("Quick answers if asked"));
  for (const line of s.ifAsked) children.push(ifAsked(line));
}

// Extra cheat sheet page
children.push(new Paragraph({ children: [new PageBreak()] }));
children.push(slideTitle("Cheat Sheet", "One-minute answers"));
children.push(label("What is ASKa-Piyu?"));
children.push(
  say(
    "A campus knowledge base plus Ask assistant plus smart ticketing so students and faculty can find authorized information and escalate concerns — with humans still deciding official actions."
  )
);
children.push(label("Is there machine learning?"));
children.push(
  say(
    "Yes, we use pretrained embeddings and LLMs for retrieval and answering. We did not train our own custom ML model. Classification is mostly rules plus similarity; reranking is rule-based."
  )
);
children.push(label("Model Evaluation in one line each"));
children.push(say("Classification: did we label the question or handbook chunk correctly?"));
children.push(say("Retrieval: did the right pages appear in the top results?"));
children.push(say("QA: is the answer correct, faithful, and relevant?"));
children.push(say("Citation: are the sources valid, precise, and complete enough?"));
children.push(label("Why RAG runner dataset empty?"));
children.push(
  say(
    "rag_eval_dataset.json was left empty on purpose until fully labeled. QA and Citation scores on the dashboard come from separate labeled/human evaluation sets."
  )
);
children.push(label("Human oversight line (memorize)"));
children.push(
  multi(
    [
      { text: "ASKa-Piyu assists with information and routing. ", bold: false },
      {
        text: "Official interpretation, approvals, payments, and records release stay with authorized personnel.",
        bold: true,
      },
    ],
    { after: 200 }
  )
);

const doc = new Document({
  styles: {
    default: {
      document: {
        styles: [{ id: "Normal", run: { font: "Calibri", size: 22 } }],
      },
    },
    paragraphStyles: [
      {
        id: "Title",
        name: "Title",
        basedOn: "Normal",
        next: "Normal",
        quickStyle: true,
        run: { font: "Calibri", size: 40, bold: true, color: "1F4E79" },
        paragraph: { spacing: { before: 0, after: 200 }, keepNext: true },
      },
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickStyle: true,
        run: { font: "Calibri", size: 32, bold: true, color: "1F4E79" },
        paragraph: { spacing: { before: 240, after: 160 }, keepNext: true },
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          margin: { top: 720, right: 720, bottom: 720, left: 720 },
        },
      },
      children,
    },
  ],
});

const out = path.join(__dirname, "ASKa_Piyu_FOD_Speaker_Script.docx");
Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(out, buffer);
  console.log("Wrote", out);
});
