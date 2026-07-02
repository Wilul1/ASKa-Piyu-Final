# ASKa-Piyu Thesis Progress Demo Script (2.5–3 minutes)

---

## **SLIDE 1: PROJECT OVERVIEW & MILESTONES** (0:00–0:30, 30 sec)

### Talking Points:
- **Project:** ASKa-Piyu — a cross-platform student support platform (web/mobile via Flutter).
- **Goal:** Provide a unified portal for students to access knowledge base, submit support tickets, and receive announcements.
- **Current Status:** **65% Complete — UI/UX Prototype Phase** ✓
  - ✅ Architecture designed & scaffolded
  - ✅ 3 core UI modules built (Home, Knowledge Base, Tickets)
  - ✅ Navigation & responsive layout implemented
  - ⏳ Backend API & persistence (Phase 2)

### Code Statistics to Display (on slide or verbally):
- **Lines of Code:** ~1,200 LoC (Dart)
- **Files:** 8 core files (5 screens + 2 widgets + 1 design system)
- **Commits:** 12+ commits (show git log if desired)
- **Framework:** Flutter (Dart) — enables iOS, Android, Web from single codebase

---

## **SLIDE 2: SYSTEM ARCHITECTURE DIAGRAM** (0:30–0:50, 20 sec)

### Visual: Show a simple architecture diagram
```
┌─────────────────────────────────────────────┐
│          Flutter Frontend (Current)         │
├─────────────────────────────────────────────┤
│  Sidebar Nav  │  Home  │  KB  │  Tickets   │
├─────────────────────────────────────────────┤
│        Local State (In-Memory, Prototype)   │
│  - TicketEntry model                       │
│  - Dynamic counts & data binding            │
├─────────────────────────────────────────────┤
│   REST API / Backend (Phase 2)             │
│   - User auth, persistence, notifications  │
└─────────────────────────────────────────────┘
```

### Talking Points:
- Modular design: sidebar navigation routes users between sections.
- Local state management for prototype; easy to swap with backend later.
- Responsive: detects screen width to show sidebar (desktop) or drawer (mobile).

---

## **LIVE DEMO SECTION** (0:50–2:30, ~100 seconds)

### **DEMO 1: HOME DASHBOARD & NAVIGATION** (0:50–1:10, 20 sec)

**Action on screen:**
1. **Open the app** in browser (already running on `localhost:PORT`).
   - Show the Home dashboard with:
     - ✅ Search bar with icon ("Search guides, tickets, and support")
     - ✅ 3 action cards (Ask ASKa-Piyu, Knowledge Base, My Tickets)
     - ✅ Popular Topics section with chips (Enrollment Process, Dropping Subjects, etc.)

2. **Narration:**
   > "This is the home dashboard. Students see a clean interface with quick-access cards. The search bar and action cards let them jump directly to features. Notice the responsive design — the sidebar collapses to a drawer on smaller screens."

3. **Demo Navigation:**
   - Click **"Knowledge Base"** card → show Knowledge Base page loads.
   - (Brief pause to show KB categories and document listings.)
   - Click **"My Tickets"** in sidebar → show My Tickets page.

---

### **DEMO 2: MY TICKETS — FEATURE SHOWCASE** (1:10–2:00, 50 sec)

**Action on screen:**
1. **Show "My Tickets" Tab (initial state):**
   - Display stat cards: **Open: 0, In-progress: 0, Closed: 0, Total: 0**
   - Show empty tickets table with message: "No tickets yet"
   - Narration:
     > "The My Tickets page starts empty. We see dynamic counters that update in real-time based on ticket data. This demonstrates our data-binding architecture — no hardcoded values."

2. **Switch to "Create Tickets" Tab:**
   - Show the create-ticket form with:
     - ✅ Category dropdown (IT, Facilities, Finance, Other)
     - ✅ Subject input field (with validation)
     - ✅ Description text area (with blue border, 6+ lines)
     - ✅ File upload button (stubbed — shows "placeholder" behavior)
     - ✅ Cancel & Submit buttons (styled in green)
   - Narration:
     > "Students submit a ticket using this form. It includes validation — all fields are required before submission. The form uses Material Design patterns for consistency."

3. **Create a Test Ticket:**
   - Fill in: Category = "IT", Subject = "Cannot login to portal", Description = "Getting error on password reset"
   - Click **Submit Ticket** button.
   - Narration:
     > "Submitting a ticket..."

4. **Switch back to "My Tickets" Tab:**
   - Show the ticket now appears in the table with:
     - ✅ Ticket ID (auto-generated: TK-xxxxx)
     - ✅ Subject and category (IT)
     - ✅ **Status badge** (colored: "Open" = blue)
     - ✅ Last updated timestamp
   - Show stat cards updated: **Open: 1, Total: 1**
   - Narration:
     > "Notice the counters updated immediately — Open is now 1, Total is 1. The ticket appears in the table with a colored status badge. This shows our state management working correctly. In production, this data would persist to a database."

---

## **CODE SNIPPET SECTION** (2:00–2:20, 20 sec)

### **Snippet 1: Ticket Model & Dynamic Counters**
Show on screen or slide:
```dart
// lib/screens/my_tickets_page.dart
class TicketEntry {
  final String id, subject, status, category, description;
  final DateTime updatedAt;
  const TicketEntry({...});
}

// Dynamic counters computed from data
final openCount = tickets.where((t) => t.status == 'Open').length;
final closedCount = tickets.where((t) => t.status == 'Closed').length;
```
**Narration:**
> "Here's our ticket model. Notice we compute open/closed counts from the actual list — no hardcoding. This is best practice for data-driven UIs."

### **Snippet 2: Form Submission Callback Pattern**
```dart
void _addTicket(TicketEntry ticket) {
  setState(() {
    _tickets.insert(0, ticket);
    _tabController.animateTo(0); // Switch to tickets tab
  });
}

// In form submit
widget.onSubmit(
  TicketEntry(id: id, subject: subject, status: 'Open', ...)
);
```
**Narration:**
> "When a user submits a ticket, we use a callback pattern to notify the parent. The parent updates the list and refreshes the UI instantly. This architecture makes it easy to later replace the in-memory list with a backend API."

---

## **TECHNICAL CHALLENGES & SOLUTIONS** (2:20–2:45, 25 sec)

### Talking Points:

1. **Challenge: Responsive Layout**
   - *Problem:* App needed to work on desktop (sidebar + content) and mobile (drawer + content) with a single codebase.
   - *Solution:* Used Flutter's `LayoutBuilder` to detect screen width and conditionally render layout.
   - *Result:* Seamless experience across devices.

2. **Challenge: Dynamic Data & State**
   - *Problem:* Initial design had hardcoded stat values (e.g., "Open: 2"). Didn't reflect actual ticket data.
   - *Solution:* Implemented `TicketEntry` model and computed counts from the list using `.where()` filters.
   - *Result:* Counters now update live when a ticket is created.

3. **Challenge: Form Validation & User Feedback**
   - *Problem:* Users need immediate feedback on form errors and submission status.
   - *Solution:* Used Flutter's `Form` + `GlobalKey` + `TextFormField` validators + `SnackBar` for feedback.
   - *Result:* Clear, accessible form that prevents invalid submissions.

### Lessons Learned:
- State management patterns (callbacks + `setState`) scale well for small prototypes; larger apps should use Riverpod/BLoC.
- Responsive UI design is easier when thought about from the start, not retrofitted.
- Centralized design tokens (`design_tokens.dart`) save time and ensure consistency.

---

## **SLIDE: PRELIMINARY RESULTS & METRICS** (2:45–3:00, 15 sec)

### Display or mention:
- **UI/UX Metrics (Prototype Phase):**
  - ✅ All 3 core screens render without errors.
  - ✅ Navigation works: Home → KB → Tickets (and back).
  - ✅ Form validation prevents invalid submissions.
  - ✅ Responsive layout adapts to screen width (tested at 900px breakpoint).
  - ✅ Status badges and counters update in real-time.

- **Code Quality:**
  - ✅ No compilation errors.
  - ✅ Consistent naming and structure across files.
  - ✅ 8 modular files (easy to maintain and extend).

- **Functional Checklist:**
  - ✅ Sidebar navigation (5 items, routable)
  - ✅ Home dashboard (search, action cards, topics)
  - ✅ Knowledge Base (categories, documents)
  - ✅ My Tickets (create, view, counters)
  - ⏳ File upload (stubbed; needs backend)
  - ⏳ Data persistence (in-memory; needs database)
  - ⏳ User authentication (Phase 2)

---

## **SLIDE: NEXT PHASE & ROADMAP** (Final ~10 sec or inline)

### Narration:
> "Phase 2 will focus on backend integration. We'll add REST API endpoints for user authentication, ticket CRUD operations, and knowledge base search. We'll also implement local database storage for offline support."

### Roadmap:
1. ✅ **Phase 1 (Current):** UI/UX Prototype — 65% complete
2. ⏳ **Phase 2 (Next):** Backend API & Authentication — ~3–4 weeks
3. ⏳ **Phase 3 (Final):** Testing, User Feedback, Refinement — ~2 weeks

---

## **KEY TALKING POINTS TO EMPHASIZE**

1. **"This is a working prototype, not a stub."** Students can actually create tickets and see live updates.
2. **"We chose Flutter for cross-platform reach."** One codebase serves web and mobile — critical for a university system.
3. **"Data-driven design."** No hardcoded values; all UI reacts to real data.
4. **"Modular & scalable architecture."** Easy to add backend without rewriting UI.
5. **"User-centered design."** Form validation, responsive layout, clear feedback (SnackBars, status badges).

---

## **TIMING SUMMARY**

| Section | Time | Duration |
|---------|------|----------|
| Milestones & Overview | 0:00–0:30 | 30 sec |
| Architecture Diagram | 0:30–0:50 | 20 sec |
| Live Demo (Home + Tickets) | 0:50–2:00 | 70 sec |
| Code Snippets | 2:00–2:20 | 20 sec |
| Challenges & Solutions | 2:20–2:45 | 25 sec |
| Results & Roadmap | 2:45–3:00 | 15 sec |
| **TOTAL** | | **~180 sec (3 min)** |

---

## **PRESENTER CHECKLIST**

Before the demo:
- ✅ App running locally: `flutter run -d chrome` (or already cached in browser)
- ✅ Have a fresh/clean app state (empty tickets list, all counters at 0)
- ✅ Slides ready (Milestones, Architecture, Code snippets, Roadmap)
- ✅ Practice creating a ticket smoothly (fill fields → submit → tab switch)
- ✅ Test responsive layout (open DevTools, toggle mobile view at 900px)
- ✅ Have backup video/GIF of demo in case of live technical issues

---

## **OPTIONAL: ADVANCED DEMO VARIATIONS**

### If you have extra 30 seconds:
- Show responsive layout: Open DevTools, resize browser to mobile width, show drawer appears.
- Show Knowledge Base navigation: Click KB card → show categories and documents.

### If someone asks about backend:
- Be ready to say: *"We're currently using in-memory state for the prototype. Phase 2 will add a Node.js/Firebase backend with user auth and persistent storage."*

### If someone asks about testing:
- Be ready to say: *"We've done manual UI testing. Phase 2 includes unit tests for form validation and integration tests for ticket creation."*

---

## **PRESENTATION TONE & NARRATIVE**

**Open with:**
> "Today I'm showing you ASKa-Piyu — a student support platform we're building with Flutter. We're 65% through our UI/UX prototype phase, and I want to walk you through the key features and the architecture decisions we made."

**Close with:**
> "By Phase 2, we'll have full backend integration. Right now, this prototype proves the concept works and gives us a solid foundation for the API. Thank you."

---

