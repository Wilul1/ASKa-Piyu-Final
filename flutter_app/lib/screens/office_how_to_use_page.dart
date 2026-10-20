import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../widgets/sidebar.dart';
import 'office_scaffold.dart';

/// In-app Office User Manual -- teaches office staff how to use the
/// existing Office Workspace (Assigned Tickets, Knowledge Base
/// extraction/indexing, and Knowledge Article). Pure documentation: it
/// renders no live ticket/article/notification data and calls no backend
/// endpoint of its own, so it can never duplicate or drift out of sync
/// with what those screens actually do. Every control, status, and step
/// named on this page was confirmed against the real frontend/backend
/// code before being written -- nothing here describes a button, state,
/// or workflow that doesn't exist.
class OfficeHowToUsePage extends StatefulWidget {
  const OfficeHowToUsePage({super.key});

  @override
  State<OfficeHowToUsePage> createState() => _OfficeHowToUsePageState();
}

class _OfficeHowToUsePageState extends State<OfficeHowToUsePage> {
  final _ticketsKey = GlobalKey();
  final _kbKey = GlobalKey();
  final _articleKey = GlobalKey();
  final _practicesKey = GlobalKey();

  void _jumpTo(GlobalKey key) {
    final ctx = key.currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(
      ctx,
      duration: const Duration(milliseconds: 280),
      curve: Curves.easeInOut,
      alignment: 0.05,
    );
  }

  @override
  Widget build(BuildContext context) {
    return OfficeScaffold(
      current: StudentNavItem.officeHowToUse,
      title: 'How to Use',
      description:
          'A plain-language guide to Assigned Tickets, Knowledge Base, and Knowledge Article in the Office Workspace.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const _IntroCard(),
          const SizedBox(height: 18),
          _TopicNav(
            onTicketsTap: () => _jumpTo(_ticketsKey),
            onKbTap: () => _jumpTo(_kbKey),
            onArticleTap: () => _jumpTo(_articleKey),
            onPracticesTap: () => _jumpTo(_practicesKey),
          ),
          const SizedBox(height: 22),
          _GuideSection(
            key: _ticketsKey,
            icon: Icons.assignment_turned_in_rounded,
            title: 'A. Assigned Tickets',
            children: const [
              _Para(
                'Assigned Tickets shows only the tickets routed to your own '
                'office. You will never see another office\'s tickets here -- '
                'this is enforced by the system, not just hidden in the UI.',
              ),
              _SubHeading('Reading the list'),
              _Para(
                'Each ticket shows a status badge: Open, In Progress, '
                'Resolved, or Closed. Use the search box and the Status / '
                'Priority filters above the list to find a specific ticket '
                'quickly.',
              ),
              _SubHeading('Opening a ticket'),
              _Steps([
                'Tap a ticket in the list to open its details.',
                'Read the student\'s original request and the full reply '
                    'thread before responding.',
                'If the ticket has attachments, open the "Attachments" '
                    'section and review each file before you reply -- it may '
                    'contain the information you need (a form, a screenshot, '
                    'a receipt).',
              ]),
              _SubHeading('Replying'),
              _Para(
                'Write a clear, professional reply addressed to the student. '
                'You can also attach a file or image to your reply (10 MB '
                'limit). If you need to leave a note for other office staff '
                'or an admin that the student should never see, mark it as '
                'an Internal Note instead of a normal reply -- internal '
                'notes are never shown to the student.',
              ),
              _SubHeading('Status: Resolve, and what you cannot do here'),
              _Bullets([
                'Status is not a dropdown you set directly. The only way to '
                    'move a ticket forward is the dedicated Resolve button, '
                    'which appears while the ticket is Open or In Progress.',
                'Priority is shown for reference but is read-only on this '
                    'page -- office staff cannot change a ticket\'s priority.',
                'You cannot reassign a ticket to a different office directly '
                    'from here either.',
              ]),
              _Callout(
                'Resolved vs. Closed: Resolved means you\'ve addressed the '
                'student\'s request. Closed is the final, archived state -- '
                'only an Admin account can close a ticket. If a resolved '
                'ticket is ready to be closed, ask an Admin.',
              ),
              _SubHeading('If a ticket belongs to another office'),
              _Para(
                'Tap the Transfer / reassign icon to open the Transfer '
                'ticket dialog, choose the destination office, and tap '
                'Apply. This only sends a transfer request -- the receiving '
                'office must accept it before the ticket actually moves. It '
                'is never an instant handoff, so the ticket stays your '
                'responsibility until the request is accepted.',
              ),
              _SubHeading('Quick decision guide'),
              _Bullets([
                'Respond: the student needs more information or you need '
                    'more information from them.',
                'Resolve: you\'ve fully answered or completed the request.',
                'Transfer: the request actually belongs to a different '
                    'office.',
                'Ask an Admin: the ticket needs to be Closed, its priority '
                    'needs to change, or it needs a direct reassignment.',
              ]),
            ],
          ),
          const SizedBox(height: 18),
          _GuideSection(
            key: _kbKey,
            icon: Icons.library_books_rounded,
            title: 'B. Knowledge Base: Extract and Index Documents',
            children: const [
              _Para(
                'This workflow feeds Ask ASKa-Piyu (the chatbot) with '
                'searchable, citable source material. It does not create a '
                'page students browse -- see the distinction at the end of '
                'this section and in Part C.',
              ),
              _Steps([
                'Open Knowledge Base from the sidebar.',
                'Choose a supported source file (PDF or image).',
                'Tap "Extract & Structure." The app runs OCR/PDF extraction, '
                    'automatic cleaning, and structuring, and shows you a '
                    'Validation Report plus a preview of the extracted text '
                    'and knowledge units.',
                'Read the Validation Report. Its status reads "Ready for '
                    'Indexing" (green) or "Needs Review" (amber), alongside '
                    'counts for missing metadata, TOC-like units, empty '
                    'units, suspicious units, and oversized chunks.',
                'Check the preview text itself for anything the metrics '
                    'might miss: missing sections, garbled characters, '
                    'duplicated passages, or content in the wrong order.',
                'If something is wrong, you can edit the extracted text '
                    'directly in the review box before indexing -- or, for '
                    'bigger problems, choose a cleaner source file and run '
                    'Extract & Structure again. There is no separate OCR '
                    'editor beyond this review box.',
                'Once you\'re satisfied, tap "Index for Chatbot Retrieval." '
                    'This saves your reviewed text as searchable knowledge '
                    'units in ChromaDB.',
                'Confirm it worked: a status message reports how many '
                    'chunks were indexed, and the statistics panel below '
                    'shows Documents indexed, Total chunks indexed, and the '
                    'most recently indexed document.',
              ]),
              _Callout(
                'If the Validation Report status reads "Needs Review," do '
                'not tap Index for Chatbot Retrieval yet. The app will not '
                'stop you -- it does not block indexing just because the '
                'status is "Needs Review" -- so this is your check to make. '
                'First inspect the preview text for the actual problem '
                '(missing content, garbled characters, duplicated or '
                'misordered passages). If it\'s fixable, correct it directly '
                'in the review box. If the source itself is too poor to fix '
                'this way, re-upload a cleaner document and run Extract & '
                'Structure again. Only index once you\'ve confirmed the '
                'text is accurate.',
              ),
              _SubHeading('If indexing fails'),
              _Para(
                'Read the error message shown on the page -- it explains '
                'what went wrong. Confirm the file is a supported PDF or '
                'image and try again. If it keeps failing, ask an Admin for '
                'help rather than repeatedly retrying.',
              ),
              _SubHeading('Verifying the indexed content is actually useful'),
              _Para(
                'Use the Retrieval Test tool on the same page: type a '
                'question the way a student would actually ask it, tap Run '
                'Retrieval Test, and check whether the content you just '
                'indexed is what comes back. Don\'t consider the job done '
                'until you\'ve tried this.',
              ),
              _Callout(
                'Extraction and indexing are not the same as creating a '
                'Knowledge Article, and neither is interchangeable with the '
                'other. Indexing puts reference material into ChromaDB for '
                'the chatbot\'s own answers and citations. It never '
                'publishes anything to the public Knowledge Base students '
                'browse -- that only happens through Knowledge Article '
                '(Part C).',
              ),
            ],
          ),
          const SizedBox(height: 18),
          _GuideSection(
            key: _articleKey,
            icon: Icons.article_outlined,
            title: 'C. Knowledge Article',
            children: const [
              _Para(
                'A Knowledge Article is a human-written page students see '
                'directly in the public Knowledge Base -- separate from the '
                'source documents and chunks you index in Part B.',
              ),
              _SubHeading('Starting a new article'),
              _Bullets([
                'Tap "Create Article" on the Knowledge Article page for a '
                    'blank form.',
                'Or, from a resolved ticket, tap "Add to KB" -- it pre-fills '
                    'the Title, Category, Summary, and Content from that '
                    'ticket so you\'re not starting from scratch. (It reads '
                    '"Update KB draft" or "KB published" once that ticket '
                    'already has an article.)',
              ]),
              _Para(
                'The form has four fields: Title, Category, Summary, and '
                'Content. Write a specific, searchable title and keep the '
                'content accurate and concise -- a short, correct answer '
                'helps students more than a long one. Double-check what '
                'you write against the official source document, not memory.',
              ),
              _Callout(
                'When you type a title, the app automatically checks for an '
                'existing article with a similar title and warns you. Read '
                'that warning before continuing -- a near-duplicate article '
                'usually means you should edit the existing one instead of '
                'publishing a second one.',
              ),
              _SubHeading('Save as draft vs. Publish Article'),
              _Para(
                '"Save as draft" keeps the article private to office/admin '
                'staff. "Publish Article" makes it visible in the public '
                'Knowledge Base immediately -- there is no separate admin '
                'approval step, so you are personally responsible for its '
                'accuracy the moment you publish.',
              ),
              _SubHeading('Editing and unpublishing'),
              _Para(
                'Open any existing article to edit its fields and save your '
                'changes. Unpublish removes it from the public Knowledge '
                'Base without deleting it -- use this if an article turns '
                'out to be wrong or outdated until you\'ve fixed it.',
              ),
            ],
          ),
          const SizedBox(height: 18),
          _GuideSection(
            key: _practicesKey,
            icon: Icons.shield_outlined,
            title: 'D. Good Practices and Troubleshooting',
            children: const [
              _SubHeading('Protect student information'),
              _Para(
                'Never paste a student\'s personal details -- ID numbers, '
                'contact information, or anything from their ticket beyond '
                'what\'s already necessary -- into a public Knowledge '
                'Article. If something sensitive needs to stay with a '
                'specific case, keep it in that ticket\'s reply or an '
                'internal note instead.',
              ),
              _SubHeading('Keep information accurate and current'),
              _Para(
                'Only write what the official source actually says. If '
                'you\'re not sure a policy or procedure is still current, '
                'verify it before publishing or replying -- don\'t guess, '
                'and don\'t assume last year\'s process still applies.',
              ),
              _SubHeading('Troubleshooting'),
              _Bullets([
                'Extraction returns poor or garbled text: re-upload a '
                    'cleaner source (a text-based PDF or a higher-resolution '
                    'scan beats a blurry photo) and re-extract; fix small '
                    'issues directly in the review box.',
                'Indexing fails: read the error message shown, confirm the '
                    'file type is supported, and try again; ask an Admin if '
                    'it keeps failing.',
                'An article seems to be missing from the Knowledge Base: '
                    'check whether it\'s still a Draft, or whether it was '
                    'Unpublished.',
                'A ticket looks like it was routed to the wrong office: use '
                    'the Transfer / reassign icon to send a transfer request '
                    '-- don\'t edit or ignore it, and don\'t expect it to '
                    'move until the other office accepts the request.',
              ]),
              _SubHeading('When to ask an Admin'),
              _Para(
                'Based on what office accounts can and cannot do in this '
                'workspace: closing a ticket, changing a ticket\'s priority, '
                'directly reassigning a ticket without a transfer request, '
                'and anything involving account or role changes all require '
                'an Admin.',
              ),
            ],
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }
}

class _IntroCard extends StatelessWidget {
  const _IntroCard();

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'This page explains how to use the tools already in your Office '
            'Workspace -- it doesn\'t add any new ticket, article, or '
            'notification features of its own. Jump to a topic below, or '
            'scroll through all four sections.',
            style: TextStyle(
              fontSize: 13.5,
              height: 1.5,
              color: DesignTokens.ink,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _TopicNav extends StatelessWidget {
  final VoidCallback onTicketsTap;
  final VoidCallback onKbTap;
  final VoidCallback onArticleTap;
  final VoidCallback onPracticesTap;

  const _TopicNav({
    required this.onTicketsTap,
    required this.onKbTap,
    required this.onArticleTap,
    required this.onPracticesTap,
  });

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: [
        _TopicChip(label: 'Assigned Tickets', onTap: onTicketsTap),
        _TopicChip(label: 'Knowledge Base', onTap: onKbTap),
        _TopicChip(label: 'Knowledge Article', onTap: onArticleTap),
        _TopicChip(label: 'Good Practices', onTap: onPracticesTap),
      ],
    );
  }
}

class _TopicChip extends StatelessWidget {
  final String label;
  final VoidCallback onTap;

  const _TopicChip({required this.label, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return Material(
      key: ValueKey('how-to-use-topic-$label'),
      color: DesignTokens.maroon.withValues(alpha: 0.07),
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
          child: Text(
            label,
            style: const TextStyle(
              fontSize: 12.5,
              fontWeight: FontWeight.w800,
              color: DesignTokens.maroon,
            ),
          ),
        ),
      ),
    );
  }
}

class _GuideSection extends StatelessWidget {
  final IconData icon;
  final String title;
  final List<Widget> children;

  const _GuideSection({
    super.key,
    required this.icon,
    required this.title,
    required this.children,
  });

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, color: DesignTokens.maroon, size: 20),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ...children,
        ],
      ),
    );
  }
}

class _Card extends StatelessWidget {
  final Widget child;

  const _Card({required this.child});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(DesignTokens.adminRadius),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: child,
    );
  }
}

class _SubHeading extends StatelessWidget {
  final String text;

  const _SubHeading(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 12, bottom: 6),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 13.5,
          fontWeight: FontWeight.w800,
          color: DesignTokens.ink,
        ),
      ),
    );
  }
}

class _Para extends StatelessWidget {
  final String text;

  const _Para(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 13,
          height: 1.55,
          color: DesignTokens.ink,
        ),
      ),
    );
  }
}

class _Steps extends StatelessWidget {
  final List<String> steps;

  const _Steps(this.steps);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (var i = 0; i < steps.length; i++)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    width: 20,
                    height: 20,
                    margin: const EdgeInsets.only(top: 1),
                    decoration: const BoxDecoration(
                      color: DesignTokens.maroon,
                      shape: BoxShape.circle,
                    ),
                    alignment: Alignment.center,
                    child: Text(
                      '${i + 1}',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      steps[i],
                      style: const TextStyle(
                        fontSize: 13,
                        height: 1.5,
                        color: DesignTokens.ink,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Bullets extends StatelessWidget {
  final List<String> items;

  const _Bullets(this.items);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final item in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: _Dot(),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      item,
                      style: const TextStyle(
                        fontSize: 13,
                        height: 1.5,
                        color: DesignTokens.ink,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Dot extends StatelessWidget {
  const _Dot();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 5,
      height: 5,
      decoration: const BoxDecoration(
        color: DesignTokens.maroon,
        shape: BoxShape.circle,
      ),
    );
  }
}

/// A single important-caution box, styled distinctly from ordinary body
/// text so staff don't skim past it -- used for the policy-level points
/// the task explicitly called out (never index unreviewed text, the
/// Resolved/Closed distinction, the duplicate-title warning).
class _Callout extends StatelessWidget {
  final String text;

  const _Callout(this.text);

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFFBD9A8)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.priority_high_rounded,
              size: 16, color: Color(0xFFB45309)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: const TextStyle(
                fontSize: 12.5,
                height: 1.5,
                fontWeight: FontWeight.w700,
                color: Color(0xFF7C3A0B),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
