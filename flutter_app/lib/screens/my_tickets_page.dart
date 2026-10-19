import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../app_config.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/login_page.dart';
import '../services/api_client.dart';
import '../services/download_file.dart';
import '../services/file_pick.dart';
import '../widgets/phone_keyboard_inset.dart';
import '../widgets/phone_layout.dart';
import '../widgets/public_site_header.dart';
import '../widgets/sidebar.dart';
import '../widgets/student_ui.dart';

const _statusOptions = ['All', 'Open', 'In Progress', 'Resolved', 'Closed'];
// Cosmetic-only display labels for _statusOptions (same indices/values) --
// the real filter value stays 'All' so comparisons/onChanged are unchanged.
const _statusOptionsDisplay = [
  'All Status',
  'Open',
  'In Progress',
  'Resolved',
  'Closed',
];

class TicketMessage {
  final String id;
  final String ticketId;
  final String senderId;
  final String senderRole;
  final String senderName;
  final String message;
  final DateTime createdAt;

  const TicketMessage({
    required this.id,
    required this.ticketId,
    required this.senderId,
    required this.senderRole,
    required this.senderName,
    required this.message,
    required this.createdAt,
  });

  factory TicketMessage.fromJson(Map<String, dynamic> json) {
    return TicketMessage(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      senderId: (json['sender_id'] ?? '').toString(),
      senderRole: (json['sender_role'] ?? 'office').toString(),
      senderName: (json['sender_name'] ?? 'Office').toString(),
      message: (json['message'] ?? '').toString(),
      createdAt: _parseDate(json['created_at']),
    );
  }
}

class TicketEntry {
  final String id;
  final String userId;
  final String userName;
  final String? userEmail;
  final String subject;
  final String status;
  final DateTime createdAt;
  final DateTime updatedAt;
  final DateTime? resolvedAt;
  final DateTime? closedAt;
  final String category;
  final String assignedOffice;
  final String priority;
  final String description;
  final double? confidenceScore;
  final bool sourceFromChatbot;
  final List<TicketMessage> messages;
  final List<_TicketAttachment> attachments;

  const TicketEntry({
    required this.id,
    required this.userId,
    required this.userName,
    required this.userEmail,
    required this.subject,
    required this.status,
    required this.createdAt,
    required this.updatedAt,
    required this.resolvedAt,
    required this.closedAt,
    required this.category,
    required this.assignedOffice,
    required this.priority,
    required this.description,
    required this.confidenceScore,
    required this.sourceFromChatbot,
    required this.messages,
    this.attachments = const [],
  });

  factory TicketEntry.fromJson(Map<String, dynamic> json) {
    final rawMessages =
        json['messages'] is List ? json['messages'] as List : const <dynamic>[];
    final rawAttachments =
        json['attachments'] is List
            ? json['attachments'] as List
            : const <dynamic>[];
    return TicketEntry(
      id: (json['ticket_id'] ?? json['id'] ?? '').toString(),
      userId: (json['user_id'] ?? '').toString(),
      userName: (json['user_name'] ?? 'Student').toString(),
      userEmail: _nullableString(json['user_email']),
      subject: (json['original_question'] ?? 'Untitled concern').toString(),
      status: _titleStatus((json['status'] ?? 'Open').toString()),
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
      resolvedAt: _parseNullableDate(json['resolved_at']),
      closedAt: _parseNullableDate(json['closed_at']),
      category: (json['category'] ?? 'General').toString(),
      assignedOffice:
          (json['assigned_office_name'] ??
                  json['assigned_office'] ??
                  'Support Office')
              .toString(),
      priority: _titlePriority((json['priority'] ?? 'Low').toString()),
      description: (json['description'] ?? '').toString(),
      confidenceScore: _parseDouble(json['confidence_score']),
      sourceFromChatbot: json['source_from_chatbot'] == true,
      messages:
          rawMessages
              .whereType<Map>()
              .map(
                (item) =>
                    TicketMessage.fromJson(Map<String, dynamic>.from(item)),
              )
              .toList(),
      attachments:
          rawAttachments
              .whereType<Map>()
              .map(
                (item) =>
                    _TicketAttachment.fromJson(Map<String, dynamic>.from(item)),
              )
              .toList(),
    );
  }

  bool matches(
    String query,
    String statusFilter, {
    String officeFilter = 'All Offices',
    String categoryFilter = 'All Categories',
  }) {
    final normalized = query.trim().toLowerCase();
    final matchesQuery =
        normalized.isEmpty ||
        id.toLowerCase().contains(normalized) ||
        subject.toLowerCase().contains(normalized) ||
        assignedOffice.toLowerCase().contains(normalized) ||
        category.toLowerCase().contains(normalized);
    final matchesStatus = statusFilter == 'All' || status == statusFilter;
    final matchesOffice =
        officeFilter == 'All Offices' || assignedOffice == officeFilter;
    final matchesCategory =
        categoryFilter == 'All Categories' || category == categoryFilter;
    return matchesQuery && matchesStatus && matchesOffice && matchesCategory;
  }
}

class MyTicketsPage extends StatefulWidget {
  final int initialTab;
  final String? initialQuestion;

  const MyTicketsPage({super.key, this.initialTab = 0, this.initialQuestion});

  @override
  State<MyTicketsPage> createState() => _MyTicketsPageState();
}

class _MyTicketsPageState extends State<MyTicketsPage>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  final List<TicketEntry> _tickets = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  String _statusFilter = 'All';
  String _officeFilter = 'All Offices';
  String _categoryFilter = 'All Categories';
  bool _requestedInitialLoad = false;
  Timer? _listPollTimer;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(
      length: 2,
      vsync: this,
      initialIndex: widget.initialTab,
    );
    _searchCtrl.addListener(() => setState(() {}));
    _tabController.addListener(() {
      if (!_tabController.indexIsChanging) setState(() {});
    });
    // Ticket-list polling only -- notifications are the Student Mailbox's
    // sole responsibility now (see StudentMailboxPage), so there is no
    // longer a second, separately-fetched notification count here to
    // keep in sync with it.
    _listPollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (!mounted || !AuthScope.of(context).isAuthenticated) return;
      if (_tabController.index != 0) return;
      _loadTickets(silent: true);
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.isAuthenticated && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _loadTickets();
        }
      });
    }
  }

  @override
  void dispose() {
    _listPollTimer?.cancel();
    _tabController.dispose();
    _searchCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadTickets({bool silent = false}) async {
    if (!silent) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not load tickets.'));
      }
      final items = data['items'] is List ? data['items'] as List : const [];
      if (!mounted) return;
      setState(() {
        _tickets
          ..clear()
          ..addAll(
            items.whereType<Map>().map(
              (item) => TicketEntry.fromJson(Map<String, dynamic>.from(item)),
            ),
          );
      });
    } catch (error) {
      if (!silent && mounted) {
        setState(() => _error = _friendlyError(error));
      }
    } finally {
      if (mounted && !silent) {
        setState(() => _loading = false);
      }
    }
  }

  void _ticketCreated(TicketEntry ticket) {
    setState(() {
      _tickets.insert(0, ticket);
      _statusFilter = 'All';
      _searchCtrl.clear();
      _tabController.animateTo(0);
    });
    _loadTickets();
  }

  void _openTicketDetails(TicketEntry ticket) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder:
            (context) => TicketDetailsPage(
              ticket: ticket,
              onUpdated: (updated) {
                setState(() {
                  final index = _tickets.indexWhere(
                    (item) => item.id == updated.id,
                  );
                  if (index >= 0) {
                    _tickets[index] = updated;
                  }
                });
              },
            ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    if (auth.isLoading) {
      return const Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        body: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }

    if (!auth.isAuthenticated) {
      return _LoginRequiredPage(
        current:
            widget.initialTab == 1
                ? StudentNavItem.submitTicket
                : StudentNavItem.myTickets,
        returnTo:
            (_) => MyTicketsPage(
              initialTab: widget.initialTab,
              initialQuestion: widget.initialQuestion,
            ),
      );
    }

    final role = auth.role;
    if (role == 'office' || role == 'admin') {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!context.mounted) return;
        redirectAfterAuth(context, role!, null);
      });
      return const Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        body: Center(
          child: CircularProgressIndicator(color: DesignTokens.maroon),
        ),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isWide = constraints.maxWidth >= 900;
        final filteredTickets = visibleTicketsForDashboard(
          _tickets,
          _searchCtrl.text,
          _statusFilter,
          officeFilter: _officeFilter,
          categoryFilter: _categoryFilter,
        );
        final officeOptions = [
          'All Offices',
          ..._distinctSorted(_tickets.map((t) => t.assignedOffice)),
        ];
        final categoryOptions = [
          'All Categories',
          ..._distinctSorted(_tickets.map((t) => t.category)),
        ];
        final hasActiveFilters =
            _searchCtrl.text.trim().isNotEmpty ||
            _statusFilter != 'All' ||
            _officeFilter != 'All Offices' ||
            _categoryFilter != 'All Categories';

        final listView = RefreshIndicator(
          onRefresh: () async {
            await _loadTickets();
          },
          color: DesignTokens.maroon,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Hidden on phones -- on a narrow screen the four stat
                // blocks either wrapped onto their own crowded rows or
                // pushed the actual ticket list well below the fold, and
                // a tablet/desktop-only overview is still just a tap away
                // via the per-ticket status chips below. Tablets and
                // desktop keep it. Uses the same phone breakpoint as the
                // rest of the site's chrome (PublicSiteHeader's own
                // narrow cutoff), not the 900px isWide used for this
                // summary's own internal grid-vs-row layout -- the two
                // are different questions (show it at all vs. how to lay
                // it out once shown). The spacing below it is skipped
                // together with the summary itself so hiding it never
                // leaves a blank gap.
                if (!isPhoneLayout(context)) ...[
                  _TicketStatsSummary(tickets: _tickets, isWide: isWide),
                  SizedBox(height: isWide ? 18 : 14),
                ],
                _TicketToolbar(
                  searchCtrl: _searchCtrl,
                  statusFilter: _statusFilter,
                  officeFilter: _officeFilter,
                  categoryFilter: _categoryFilter,
                  officeOptions: officeOptions,
                  categoryOptions: categoryOptions,
                  onStatusChanged:
                      (value) => setState(() => _statusFilter = value),
                  onOfficeChanged:
                      (value) => setState(() => _officeFilter = value),
                  onCategoryChanged:
                      (value) => setState(() => _categoryFilter = value),
                  hasActiveFilters: hasActiveFilters,
                  onClear:
                      () => setState(() {
                        _searchCtrl.clear();
                        _statusFilter = 'All';
                        _officeFilter = 'All Offices';
                        _categoryFilter = 'All Categories';
                      }),
                ),
                SizedBox(height: isWide ? 16 : 12),
                if (_loading && _tickets.isEmpty)
                  const TicketLoadingState()
                else if (_error != null)
                  _TicketError(message: _error!, onRetry: _loadTickets)
                else
                  TicketsList(
                    tickets: filteredTickets,
                    hasAnyTickets: _tickets.isNotEmpty,
                    onTicketTap: _openTicketDetails,
                    onSubmitTicket: () => _tabController.animateTo(1),
                  ),
              ],
            ),
          ),
        );

        final submitView = SingleChildScrollView(
          child: CreateTicketForm(
            initialQuestion: widget.initialQuestion,
            onCreated: _ticketCreated,
            compact: !isWide,
          ),
        );

        final bodyContent = StudentPage(
          maxWidth: 1780,
          scroll: isWide,
          padding:
              isWide
                  ? const EdgeInsets.fromLTRB(24, 22, 24, 28)
                  : const EdgeInsets.fromLTRB(16, 12, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Neither tab shows a "Back to ..." row above the heading --
              // the navbar's own My Tickets nav item (kept active on both
              // tabs) already provides navigation.
              //
              // Both tabs use a small, plain-text heading -- no wave art,
              // colored panel, eyebrow label, or introductory paragraph --
              // matching the simple HESK-style "View existing ticket"
              // reference this list was redesigned against. The List view
              // previously had its own much larger decorative hero; the
              // status summary and ticket list below now speak for
              // themselves instead of a header introducing them.
              AnimatedBuilder(
                animation: _tabController,
                builder: (context, _) {
                  if (_tabController.index == 1) {
                    return _SubmitTicketCompactBanner(isWide: isWide);
                  }
                  return _MyTicketsCompactHeading(
                    isWide: isWide,
                    onSubmitTicket: () => _tabController.animateTo(1),
                  );
                },
              ),
              SizedBox(height: isWide ? 20 : 14),
              if (isWide)
                SizedBox(
                  height: 760,
                  child: TabBarView(
                    controller: _tabController,
                    children: [listView, submitView],
                  ),
                )
              else
                Expanded(
                  child: TabBarView(
                    controller: _tabController,
                    children: [listView, submitView],
                  ),
                ),
            ],
          ),
        );

        return Scaffold(
          backgroundColor: DesignTokens.bgGrey,
          body: Column(
            children: [
              const PublicSiteHeader(myTicketsActive: true),
              Expanded(child: bodyContent),
            ],
          ),
        );
      },
    );
  }
}

List<String> _distinctSorted(Iterable<String> values) {
  final set = <String>{};
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) set.add(trimmed);
  }
  final list = set.toList()..sort();
  return list;
}

/// Tickets to show in the dashboard list for the given search/filters --
/// [TicketEntry.matches] plus one extra dashboard-only default: a
/// Resolved ticket is left out unless the student has explicitly picked
/// the "Resolved" status filter (`statusFilter != 'All'` already implies
/// `matches` has filtered everything else out, so this only narrows the
/// "All Status" case). Closed tickets are never hidden by this --
/// Resolved and Closed are two distinct, independent terminal statuses
/// in this app (separate backend columns/timestamps, a dedicated
/// 4-value CHECK constraint, their own filter options and chip colors),
/// not synonyms. A standalone top-level function so this exact behavior
/// is directly testable without a running page/backend.
@visibleForTesting
List<TicketEntry> visibleTicketsForDashboard(
  List<TicketEntry> tickets,
  String query,
  String statusFilter, {
  required String officeFilter,
  required String categoryFilter,
}) {
  return tickets
      .where(
        (ticket) => ticket.matches(
          query,
          statusFilter,
          officeFilter: officeFilter,
          categoryFilter: categoryFilter,
        ),
      )
      .where((ticket) => statusFilter != 'All' || ticket.status != 'Resolved')
      .toList();
}

/// My Tickets' own compact heading -- a small icon and the page title,
/// nothing else. No wave art, colored panel, eyebrow label, or
/// introductory paragraph (the List view previously had a much larger
/// decorative hero with both, closer to a marketing banner than a plain
/// list header -- the HESK mobile reference's own simple "View existing
/// ticket" icon-and-title header was the target this replaced it with).
class _MyTicketsCompactHeading extends StatelessWidget {
  final bool isWide;
  final VoidCallback onSubmitTicket;

  const _MyTicketsCompactHeading({
    required this.isWide,
    required this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    final titleText = Text(
      'My Tickets',
      style: TextStyle(
        fontSize: isWide ? 28 : 20,
        fontWeight: FontWeight.w900,
        color: DesignTokens.maroon,
        height: 1.1,
      ),
    );

    // Reuses the page's own submit flow (the Submit Ticket tab) --
    // there is no second/duplicate submission path here, just another
    // entry point into the same one.
    final submitButton = SizedBox(
      height: 40,
      width: isWide ? null : double.infinity,
      child: ElevatedButton(
        onPressed: onSubmitTicket,
        style: ElevatedButton.styleFrom(
          backgroundColor: DesignTokens.maroon,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 22),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        ),
        child: const Text(
          'Submit Ticket',
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
        ),
      ),
    );

    return Padding(
      padding: EdgeInsets.fromLTRB(
        isWide ? 28 : 18,
        isWide ? 18 : 10,
        isWide ? 28 : 18,
        0,
      ),
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: isWide ? 20 : 14,
          vertical: isWide ? 16 : 12,
        ),
        // Restrained rose tint + a gentle matching border -- just enough
        // surface definition to stop the page from reading as flat white
        // on grey, without becoming a banner (no gradient, no wave art,
        // minimal padding).
        decoration: BoxDecoration(
          color: DesignTokens.maroon.withValues(alpha: 0.045),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: DesignTokens.maroon.withValues(alpha: 0.12)),
        ),
        child:
            isWide
                ? Row(
                  children: [
                    titleText,
                    const Spacer(),
                    submitButton,
                  ],
                )
                // Stacked on phones -- a title row plus an inline button
                // wide enough to tap comfortably would either overflow or
                // force the button down to an awkward width; full-width
                // below the heading avoids both.
                : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [titleText, const SizedBox(height: 12), submitButton],
                ),
      ),
    );
  }
}

/// Submit Ticket's own, deliberately small banner -- no wave art, no
/// colored background panel, no eyebrow label. On a phone, the old full
/// decorative hero pushed the actual form fields well below the fold
/// (HESK's own mobile submit form was the layout reference for keeping
/// the form itself near the top); this keeps the page title and
/// ASKa-Piyu's maroon brand color while cutting the decorative height
/// that didn't serve that goal. Still plain text on the page background,
/// not a card -- the form card right below it is the page's only
/// bordered panel.
class _SubmitTicketCompactBanner extends StatelessWidget {
  final bool isWide;

  const _SubmitTicketCompactBanner({required this.isWide});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.fromLTRB(
        isWide ? 28 : 18,
        isWide ? 18 : 10,
        isWide ? 28 : 18,
        0,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            'Submit a Support Request',
            style: TextStyle(
              fontSize: isWide ? 28 : 20,
              fontWeight: FontWeight.w900,
              color: DesignTokens.maroon,
              height: 1.1,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            'Tell us what you need help with.',
            style: TextStyle(
              fontSize: isWide ? 14 : 13,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}

class _LoginRequiredPage extends StatelessWidget {
  final StudentNavItem current;
  final WidgetBuilder returnTo;

  const _LoginRequiredPage({required this.current, required this.returnTo});

  @override
  Widget build(BuildContext context) {
    final content = StudentPage(
      maxWidth: 620,
      child: StudentPanel(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const StudentIconBox(
              icon: Icons.lock_person_rounded,
              color: DesignTokens.maroon,
              size: 56,
            ),
            const SizedBox(height: 18),
            const Text(
              'Login required',
              style: TextStyle(
                color: DesignTokens.ink,
                fontSize: 26,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              loginRequiredMessage,
              style: TextStyle(color: DesignTokens.muted, height: 1.45),
            ),
            const SizedBox(height: 22),
            ElevatedButton(
              onPressed:
                  () => Navigator.of(context).pushReplacement(
                    MaterialPageRoute(
                      builder:
                          (_) => LoginPage(
                            returnTo: returnTo,
                            message: loginRequiredMessage,
                          ),
                    ),
                  ),
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                elevation: 0,
                padding: const EdgeInsets.symmetric(vertical: 15),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(14),
                ),
              ),
              child: const Text('Login or Create Account'),
            ),
          ],
        ),
      ),
    );

    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      body: Column(
        children: [
          const PublicSiteHeader(myTicketsActive: true),
          Expanded(child: content),
        ],
      ),
    );
  }
}

/// Real ticket counts presented as plain numbers/labels -- no status icons
/// or icon containers, per the redesign's "typography over icons" mandate.
/// This panel only ever renders on tablet/desktop (see the
/// `isPhoneLayout` guard at its call site), so its own Submit Ticket
/// button was dropped once the compact heading above gained one that's
/// visible at every width -- two buttons for the same action would have
/// been clutter, not personality.
class _TicketStatsSummary extends StatelessWidget {
  final List<TicketEntry> tickets;
  final bool isWide;

  const _TicketStatsSummary({required this.tickets, required this.isWide});

  @override
  Widget build(BuildContext context) {
    final openCount = tickets.where((t) => t.status == 'Open').length;
    final progressCount =
        tickets.where((t) => t.status == 'In Progress').length;
    final closedCount = tickets.where((t) => t.status == 'Closed').length;
    final totalCount = tickets.length;

    final metrics = [
      (
        number: '$openCount',
        label: 'Open',
        caption: 'Awaiting office response',
        color: const Color(0xFF2563EB),
      ),
      (
        number: '$progressCount',
        label: 'In Progress',
        caption: 'Being handled by the office',
        color: const Color(0xFFF97316),
      ),
      (
        number: '$closedCount',
        label: 'Closed',
        caption: 'Resolved tickets',
        color: const Color(0xFF16A34A),
      ),
      (
        number: '$totalCount',
        label: 'Total',
        caption: 'All time tickets',
        color: DesignTokens.maroon,
      ),
    ];

    final blocks = [
      for (final m in metrics)
        _StatBlock(
          number: m.number,
          label: m.label,
          caption: m.caption,
          color: m.color,
        ),
    ];

    // Wide layout: a single row with a subtle vertical divider between each
    // metric, matching the approved target's summary card exactly.
    // IntrinsicHeight is required here: VerticalDivider wants to fill all
    // available height, which is unbounded inside this scrollable column,
    // so without it the layout throws a "RenderBox was not laid out"
    // assertion.
    final wideStatsRow = IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < blocks.length; i++) ...[
            if (i > 0)
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 18),
                child: VerticalDivider(
                  width: 1,
                  thickness: 1,
                  color: DesignTokens.border,
                ),
              ),
            Expanded(child: blocks[i]),
          ],
        ],
      ),
    );

    // Fixed 2x2 grid on mobile (Open/In Progress on top, Closed/Total below)
    // -- previously this fell back to a single stacked column because the
    // page's own horizontal padding left less than 380px of content width
    // at common phone sizes (e.g. ~358px at a 390px viewport), so the old
    // ">= 380" threshold never actually triggered on a real phone.
    final narrowStatsGrid = StudentResponsiveWrap(
      columns: 2,
      spacing: 10,
      children: [
        for (final m in metrics)
          _StatBlock(
            number: m.number,
            label: m.label,
            caption: m.caption,
            color: m.color,
            compact: true,
          ),
      ],
    );

    return StudentPanel(
      padding: EdgeInsets.symmetric(
        horizontal: isWide ? 20 : 14,
        vertical: isWide ? 12 : 14,
      ),
      child: isWide ? wideStatsRow : narrowStatsGrid,
    );
  }
}

class _StatBlock extends StatelessWidget {
  final String number;
  final String label;
  final String caption;
  final Color color;
  // Mobile-only density tweak: slightly smaller number, and the caption
  // wraps to 2 lines instead of truncating to 1 -- the desktop card (the
  // default, compact: false) is completely unchanged.
  final bool compact;

  const _StatBlock({
    required this.number,
    required this.label,
    required this.caption,
    required this.color,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 10 : 12,
        vertical: compact ? 8 : 8,
      ),
      decoration: BoxDecoration(
        // A very subtle per-metric tint (matching the target) -- not a
        // solid fill, just enough to distinguish each metric's zone.
        color: color.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            number,
            style: TextStyle(
              fontSize: compact ? 20 : 24,
              fontWeight: FontWeight.w900,
              color: color,
              height: 1,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12.5,
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            caption,
            maxLines: compact ? 2 : 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 11,
              color: DesignTokens.muted,
              height: 1.2,
            ),
          ),
        ],
      ),
    );
  }
}

/// Search + filters toolbar. Status filtering preserves the real existing
/// values; Office/Category filtering is new but derived entirely from
/// already-loaded ticket data (no API/backend change) per the redesign
/// brief. Text-based Refresh/Clear actions replace the old icon buttons.
/// Search + filters toolbar. On desktop this renders as the single row
/// shown in the approved target (search, Status, Offices, Categories,
/// Clear); narrower widths stack it. Manual pull-to-refresh remains fully
/// available via the page's own [RefreshIndicator] (swipe-to-refresh),
/// which this toolbar never controlled -- only the separate, always-
/// visible "Refresh" text button (added in an earlier pass, not present
/// in the approved target) has been removed here.
class _TicketToolbar extends StatefulWidget {
  final TextEditingController searchCtrl;
  final String statusFilter;
  final String officeFilter;
  final String categoryFilter;
  final List<String> officeOptions;
  final List<String> categoryOptions;
  final ValueChanged<String> onStatusChanged;
  final ValueChanged<String> onOfficeChanged;
  final ValueChanged<String> onCategoryChanged;
  final bool hasActiveFilters;
  final VoidCallback onClear;

  const _TicketToolbar({
    required this.searchCtrl,
    required this.statusFilter,
    required this.officeFilter,
    required this.categoryFilter,
    required this.officeOptions,
    required this.categoryOptions,
    required this.onStatusChanged,
    required this.onOfficeChanged,
    required this.onCategoryChanged,
    required this.hasActiveFilters,
    required this.onClear,
  });

  @override
  State<_TicketToolbar> createState() => _TicketToolbarState();
}

class _TicketToolbarState extends State<_TicketToolbar> {
  // Mobile-only presentation state: whether the advanced filters (Status /
  // Office / Category / Clear) are expanded below Search. Purely a UI
  // disclosure toggle -- the actual filter VALUES always live in the
  // parent's state (via widget.statusFilter etc.), so collapsing this never
  // resets a selection; it only hides/shows the controls that edit it.
  bool _filtersExpanded = false;

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      shadow: false,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isNarrow = constraints.maxWidth < 900;
          // A tighter content padding than the shared `_inputDecoration`
          // default -- scoped to this toolbar only via `.copyWith` so
          // Submit Ticket's own fields (which also use `_inputDecoration`)
          // are not affected.
          final searchField = TextField(
            controller: widget.searchCtrl,
            decoration: _inputDecoration(
              hintText: 'Search ticket ID, subject, office, or category...',
            ).copyWith(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
            ),
          );
          final statusDropdown = _FilterDropdown(
            label: 'All Status',
            value: widget.statusFilter,
            values: _statusOptions,
            displayValues: _statusOptionsDisplay,
            onChanged: widget.onStatusChanged,
          );
          final officeDropdown = _FilterDropdown(
            label: 'All Offices',
            value: widget.officeFilter,
            values: widget.officeOptions,
            onChanged: widget.onOfficeChanged,
          );
          final categoryDropdown = _FilterDropdown(
            label: 'All Categories',
            value: widget.categoryFilter,
            values: widget.categoryOptions,
            onChanged: widget.onCategoryChanged,
          );
          final clearAction = TextButton(
            onPressed: widget.hasActiveFilters ? widget.onClear : null,
            style: TextButton.styleFrom(
              backgroundColor: const Color(0xFFFBF2F3),
              foregroundColor: DesignTokens.maroon,
              padding: const EdgeInsets.symmetric(horizontal: 16),
              minimumSize: const Size(0, 0),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
            ),
            child: const Text('Clear'),
          );

          if (isNarrow) {
            // Advanced filters (Status/Office/Category/Clear) are collapsed
            // by default so ticket cards appear sooner on mobile -- Search
            // stays visible and fully usable either way. The count reflects
            // active SELECTIONS, not matching tickets, and never includes
            // Search (Search is not part of the collapsible section).
            final activeAdvancedCount =
                (widget.statusFilter != 'All' ? 1 : 0) +
                (widget.officeFilter != 'All Offices' ? 1 : 0) +
                (widget.categoryFilter != 'All Categories' ? 1 : 0);
            final toggleLabel =
                _filtersExpanded
                    ? 'Hide filters'
                    : activeAdvancedCount > 0
                    ? 'Filters ($activeAdvancedCount)'
                    : 'Filters';

            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                searchField,
                const SizedBox(height: 8),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton(
                    onPressed:
                        () => setState(
                          () => _filtersExpanded = !_filtersExpanded,
                        ),
                    style: TextButton.styleFrom(
                      foregroundColor: DesignTokens.maroon,
                      visualDensity: VisualDensity.compact,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4,
                        vertical: 6,
                      ),
                    ),
                    child: Text(
                      toggleLabel,
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ),
                if (_filtersExpanded) ...[
                  const SizedBox(height: 4),
                  statusDropdown,
                  const SizedBox(height: 10),
                  officeDropdown,
                  const SizedBox(height: 10),
                  categoryDropdown,
                  const SizedBox(height: 10),
                  Align(alignment: Alignment.centerRight, child: clearAction),
                ],
              ],
            );
          }

          // IntrinsicHeight is required: CrossAxisAlignment.stretch needs a
          // bounded cross-axis (height) size to stretch into, which a bare
          // Row can't provide inside this unbounded-height scrollable
          // column -- without it this throws the same class of layout
          // assertion as an unwrapped VerticalDivider would.
          return IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Expanded(flex: 6, child: searchField),
                const SizedBox(width: 10),
                SizedBox(width: 150, child: statusDropdown),
                const SizedBox(width: 10),
                SizedBox(width: 170, child: officeDropdown),
                const SizedBox(width: 10),
                SizedBox(width: 170, child: categoryDropdown),
                const SizedBox(width: 10),
                clearAction,
              ],
            ),
          );
        },
      ),
    );
  }
}

/// [displayValues], when given, supplies the visible label for each entry
/// in [values] at the same index -- purely cosmetic (e.g. showing "All
/// Status" for the real underlying filter value "All") so the real value
/// used for equality checks/onChanged is never renamed.
class _FilterDropdown extends StatelessWidget {
  final String label;
  final String value;
  final List<String> values;
  final List<String>? displayValues;
  final ValueChanged<String> onChanged;

  const _FilterDropdown({
    required this.label,
    required this.value,
    required this.values,
    this.displayValues,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    // A subtle rose fill + border when a non-default value is picked --
    // a quiet "this filter is active" cue (color/border only, no icon
    // or badge) instead of the same neutral look whether or not the
    // student has actually narrowed the list.
    final isActive = values.isNotEmpty && value != values.first;
    return DropdownButtonFormField<String>(
      value: value,
      isExpanded: true,
      decoration: _inputDecoration(hintText: label).copyWith(
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 10,
        ),
        fillColor: isActive ? const Color(0xFFFBF2F3) : null,
        enabledBorder:
            isActive
                ? OutlineInputBorder(
                  borderRadius: BorderRadius.circular(14),
                  borderSide: BorderSide(
                    color: DesignTokens.maroon.withValues(alpha: 0.35),
                  ),
                )
                : null,
      ),
      items: [
        for (var i = 0; i < values.length; i++)
          DropdownMenuItem(
            value: values[i],
            child: Text(
              displayValues != null ? displayValues![i] : values[i],
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
      onChanged: (value) {
        if (value != null) onChanged(value);
      },
    );
  }
}

class TicketsList extends StatelessWidget {
  final List<TicketEntry> tickets;
  final bool hasAnyTickets;
  final ValueChanged<TicketEntry> onTicketTap;
  final VoidCallback onSubmitTicket;

  const TicketsList({
    super.key,
    required this.tickets,
    required this.hasAnyTickets,
    required this.onTicketTap,
    required this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    if (tickets.isEmpty) {
      return TicketEmptyState(
        title: hasAnyTickets ? 'No matching tickets' : 'No tickets yet',
        message:
            hasAnyTickets
                ? 'Try changing the search text, status, or priority filter.'
                : 'Submitted support requests will appear here with status updates and office replies.',
        // A student with filtered-out tickets already has tickets --
        // "Submit a Ticket" belongs here only for the genuinely-empty
        // (never submitted one) state, not as a redundant prompt on top
        // of an active filter.
        onSubmitTicket: hasAnyTickets ? null : onSubmitTicket,
      );
    }

    return Column(
      children:
          tickets
              .map(
                (ticket) => Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: TicketCard(
                    ticket: ticket,
                    onTap: () => onTicketTap(ticket),
                  ),
                ),
              )
              .toList(),
    );
  }
}

/// Compact card: the ticket ID is the card's primary text -- not the
/// subject -- alongside the status chip and when it last updated, with
/// a trailing chevron for drill-down. The subject, priority, office/
/// category, reply counts, and a description preview (all still visible
/// once a ticket is opened, and still fully searchable/filterable) were
/// dropped from this list view; a row of secondary metadata on every
/// card was more to scan, not less, and didn't serve the "clean,
/// compact" goal this list is for. One row at every width -- a short
/// ticket ID never needed the old subject-driven narrow/wide stacking.
class TicketCard extends StatelessWidget {
  final TicketEntry ticket;
  final VoidCallback onTap;

  const TicketCard({super.key, required this.ticket, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return StudentInkCard(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // A slim rose/burgundy accent bar -- color and shape, not
            // an icon -- in place of the removed ticket-icon badge.
            // Stretches to the row's own content height, so it never
            // adds vertical space on its own.
            Container(
              width: 4,
              decoration: BoxDecoration(
                color: DesignTokens.maroon.withValues(alpha: 0.35),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    ticket.id,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: DesignTokens.maroon,
                      fontWeight: FontWeight.w900,
                      fontSize: 16,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatDate(ticket.updatedAt),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 12.5,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Center(child: TicketStatusChip(status: ticket.status)),
            const SizedBox(width: 6),
            const Center(
              child: Icon(
                Icons.chevron_right_rounded,
                color: DesignTokens.muted,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class TicketDetailsPage extends StatefulWidget {
  final TicketEntry ticket;
  final ValueChanged<TicketEntry>? onUpdated;

  const TicketDetailsPage({super.key, required this.ticket, this.onUpdated});

  @override
  State<TicketDetailsPage> createState() => _TicketDetailsPageState();
}

class _TicketDetailsPageState extends State<TicketDetailsPage> {
  late TicketEntry _ticket;
  final TextEditingController _replyController = TextEditingController();
  final ScrollController _conversationScroll = ScrollController();
  bool _sending = false;
  bool _attaching = false;
  bool _refreshing = false;
  bool _phoneThreadOpen = false;
  String? _replyError;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _ticket = widget.ticket;
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      if (mounted) _refreshTicket(silent: true);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _refreshTicket(silent: true);
    });
    bindVisualViewportListener(_onKeyboardInset);
  }

  void _onKeyboardInset() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    unbindVisualViewportListener(_onKeyboardInset);
    _pollTimer?.cancel();
    _replyController.dispose();
    _conversationScroll.dispose();
    super.dispose();
  }

  bool get _canStudentReply {
    final status = _ticket.status;
    return status == 'Open' || status == 'In Progress' || status == 'Resolved';
  }

  Future<void> _refreshTicket({bool silent = false}) async {
    if (_refreshing) return;
    _refreshing = true;
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      if (result.statusCode < 200 || result.statusCode >= 300 || !mounted) {
        return;
      }
      final updated = TicketEntry.fromJson(data);
      final changed =
          updated.messages.length != _ticket.messages.length ||
          updated.attachments.length != _ticket.attachments.length ||
          updated.status != _ticket.status ||
          updated.updatedAt != _ticket.updatedAt;
      if (!changed) return;
      setState(() => _ticket = updated);
      widget.onUpdated?.call(updated);
      if (_conversationScroll.hasClients) {
        await Future<void>.delayed(const Duration(milliseconds: 50));
        if (_conversationScroll.hasClients) {
          _conversationScroll.animateTo(
            _conversationScroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOut,
          );
        }
      }
    } catch (_) {
      if (!silent && mounted) {
        // Keep current ticket visible; live refresh failures are non-blocking.
      }
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _sendReply() async {
    final message = _replyController.text.trim();
    if (message.isEmpty || _sending || !_canStudentReply) return;
    setState(() {
      _sending = true;
      _replyError = null;
    });
    try {
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/replies',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: {'message': message},
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not send your reply.'));
      }
      final updated = TicketEntry.fromJson(data);
      setState(() {
        _ticket = updated;
        _replyController.clear();
      });
      widget.onUpdated?.call(updated);
    } catch (error) {
      if (!mounted) return;
      setState(() => _replyError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _pickAndUploadAttachment({required bool imagesOnly}) async {
    if (!_canStudentReply || _attaching || _sending) return;
    try {
      final picked = await pickAppFile(
        allowedExtensions:
            imagesOnly
                ? const ['png', 'jpg', 'jpeg', 'gif', 'webp']
                : const ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
        dialogTitle: imagesOnly ? 'Attach image' : 'Attach file (PDF or image)',
      );
      if (picked == null || !mounted) return;
      if (picked.bytes.length > 10 * 1024 * 1024) {
        setState(() => _replyError = 'Attachment must be 10 MB or smaller.');
        return;
      }
      setState(() {
        _attaching = true;
        _replyError = null;
      });
      final headers = AuthScope.of(context).ticketHeaders();
      final result = await ApiClient.multipart(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/attachments',
        headers: headers,
        files: [
          http.MultipartFile.fromBytes(
            'file',
            picked.bytes,
            filename: picked.name,
          ),
        ],
      );
      if (result.statusCode < 200 || result.statusCode >= 300) {
        final data = _decodeObject(result.body);
        throw StateError(_extractError(data, 'Attachment upload failed.'));
      }
      final refresh = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}',
        headers: headers,
      );
      final data = _decodeObject(refresh.body);
      if (refresh.statusCode >= 200 && refresh.statusCode < 300 && mounted) {
        final updated = TicketEntry.fromJson(data);
        setState(() => _ticket = updated);
        widget.onUpdated?.call(updated);
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('Attached ${picked.name}'),
        ),
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _replyError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _attaching = false);
    }
  }

  Future<void> _downloadAttachment(_TicketAttachment file) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}${file.downloadUrl}',
        headers: AuthScope.of(context).ticketHeaders(),
        asBytes: true,
      );
      if (!result.ok) {
        throw StateError('Could not download file.');
      }
      await downloadBytesFile(
        filename: file.originalFilename,
        bytes: result.bytes,
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: const Color(0xFF991B1B),
          content: Text(_friendlyError(error)),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final ticket = _ticket;
    final officeReplies =
        ticket.messages
            .where((message) => message.senderRole.toLowerCase() != 'student')
            .length;
    final isWide = MediaQuery.sizeOf(context).width >= 960;
    final phone = MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint;

    final detailsPanel = _TicketDetailsSidePanel(ticket: ticket);
    final conversation = Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (!(phone && _phoneThreadOpen))
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              children: [
                Text(
                  'Conversation',
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
                const Spacer(),
                Text(
                  '$officeReplies office ${officeReplies == 1 ? 'reply' : 'replies'}',
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                IconButton(
                  tooltip: 'Refresh',
                  onPressed: () => _refreshTicket(),
                  icon: const Icon(Icons.refresh_rounded, size: 20),
                ),
              ],
            ),
          ),
        if (!(phone && _phoneThreadOpen)) const Divider(height: 1),
        Expanded(
          child: ConversationTimeline(
            ticket: ticket,
            scrollController: _conversationScroll,
            onDownloadAttachment: _downloadAttachment,
          ),
        ),
        if (_canStudentReply)
          _TicketReplyComposer(
            key: const Key('student-reply-composer'),
            controller: _replyController,
            sending: _sending,
            attaching: _attaching,
            error: _replyError,
            onSend: _sendReply,
            onAttachImage: () => _pickAndUploadAttachment(imagesOnly: true),
            onAttachFile: () => _pickAndUploadAttachment(imagesOnly: false),
          )
        else
          Container(
            width: double.infinity,
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 16),
            decoration: const BoxDecoration(
              color: Color(0xFFF8FAFC),
              border: Border(top: BorderSide(color: DesignTokens.border)),
            ),
            child: Text(
              ticket.status == 'Closed'
                  ? 'This ticket is closed. Open a new request if you still need help.'
                  : 'Replies are unavailable for this ticket status.',
              style: const TextStyle(color: DesignTokens.muted, height: 1.4),
            ),
          ),
      ],
    );

    final body = Padding(
      padding: EdgeInsets.fromLTRB(
        phone ? 12 : 20,
        phone ? 8 : 16,
        phone ? 12 : 20,
        phone ? 8 : 20,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              TextButton.icon(
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.arrow_back_rounded, size: 18),
                label: Text(phone ? 'Back' : 'Back to My Tickets'),
              ),
              const Spacer(),
              TicketStatusChip(status: ticket.status),
              const SizedBox(width: 8),
              TicketPriorityChip(priority: ticket.priority),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            ticket.id,
            style: const TextStyle(
              color: DesignTokens.maroon,
              fontWeight: FontWeight.w800,
              fontSize: 12,
              letterSpacing: 0.2,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            ticket.subject,
            maxLines: phone ? 2 : 4,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: phone ? 17 : 24,
              height: 1.25,
            ),
          ),
          SizedBox(height: phone ? 8 : 16),
          Expanded(
            child:
                isWide
                    ? Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(
                          flex: 7,
                          child: StudentPanel(
                            shadow: false,
                            padding: EdgeInsets.zero,
                            child: conversation,
                          ),
                        ),
                        const SizedBox(width: 16),
                        SizedBox(width: 320, child: detailsPanel),
                      ],
                    )
                    : Column(
                      children: [
                        Theme(
                          data: Theme.of(
                            context,
                          ).copyWith(dividerColor: Colors.transparent),
                          child: StudentPanel(
                            shadow: false,
                            padding: EdgeInsets.zero,
                            child: ExpansionTile(
                              initiallyExpanded: false,
                              tilePadding: const EdgeInsets.symmetric(
                                horizontal: 12,
                                vertical: 0,
                              ),
                              childrenPadding: const EdgeInsets.fromLTRB(
                                12,
                                0,
                                12,
                                12,
                              ),
                              title: const Text(
                                'Ticket details',
                                style: TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 14,
                                  color: DesignTokens.ink,
                                ),
                              ),
                              subtitle: Text(
                                '${ticket.category} · ${ticket.assignedOffice}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  color: DesignTokens.muted,
                                  fontSize: 12,
                                ),
                              ),
                              children: [
                                _TicketDetailsSidePanel(
                                  ticket: ticket,
                                  embed: true,
                                ),
                              ],
                            ),
                          ),
                        ),
                        const SizedBox(height: 10),
                        Expanded(
                          child: _PhoneConversationLaunchCard(
                            ticket: ticket,
                            officeReplies: officeReplies,
                            onOpen:
                                () => setState(() => _phoneThreadOpen = true),
                          ),
                        ),
                      ],
                    ),
          ),
        ],
      ),
    );

    if (phone && _phoneThreadOpen) {
      // Web keyboards often do not update MediaQuery alone. Pad with the
      // shared inset and keep resizeToAvoidBottomInset off so the gap does
      // not double when the inset returns to zero.
      return Scaffold(
        backgroundColor: DesignTokens.bgGrey,
        resizeToAvoidBottomInset: false,
        body: Padding(
          padding: EdgeInsets.only(bottom: phoneKeyboardInset(context)),
          child: Column(
            children: [
              SafeArea(
                bottom: false,
                child: Material(
                  color: Colors.white,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(4, 4, 12, 8),
                    child: Row(
                      children: [
                        IconButton(
                          tooltip: 'Back to ticket',
                          onPressed:
                              () => setState(() => _phoneThreadOpen = false),
                          icon: const Icon(Icons.arrow_back_rounded),
                        ),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'Conversation',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: DesignTokens.muted,
                                ),
                              ),
                              Text(
                                ticket.subject,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w800,
                                  fontSize: 15,
                                  color: DesignTokens.ink,
                                ),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          tooltip: 'Refresh',
                          onPressed: () => _refreshTicket(),
                          icon: const Icon(Icons.refresh_rounded, size: 20),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              Expanded(
                child: ColoredBox(color: Colors.white, child: conversation),
              ),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      resizeToAvoidBottomInset: false,
      body: Column(
        children: [
          if (!(phone && phoneKeyboardInset(context) > 48))
            const PublicSiteHeader(myTicketsActive: true),
          Expanded(child: body),
        ],
      ),
    );
  }
}

class _PhoneConversationLaunchCard extends StatelessWidget {
  final TicketEntry ticket;
  final int officeReplies;
  final VoidCallback onOpen;

  const _PhoneConversationLaunchCard({
    required this.ticket,
    required this.officeReplies,
    required this.onOpen,
  });

  String get _preview {
    if (ticket.messages.isNotEmpty) {
      return ticket.messages.last.message.trim();
    }
    return ticket.description.trim();
  }

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      shadow: false,
      padding: EdgeInsets.zero,
      child: Material(
        color: Colors.white,
        child: InkWell(
          onTap: onOpen,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 12, 16),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Conversation',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 15,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        officeReplies == 0
                            ? 'No office replies yet · Tap to open'
                            : '$officeReplies office ${officeReplies == 1 ? 'reply' : 'replies'} · Tap to open',
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      if (_preview.isNotEmpty) ...[
                        const SizedBox(height: 10),
                        Text(
                          _preview,
                          maxLines: 4,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: DesignTokens.ink,
                            height: 1.4,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  color: DesignTokens.maroon,
                  size: 28,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _TicketDetailsSidePanel extends StatelessWidget {
  final TicketEntry ticket;
  final bool embed;

  const _TicketDetailsSidePanel({required this.ticket, this.embed = false});

  @override
  Widget build(BuildContext context) {
    final content = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!embed) ...[
          const Text(
            'Ticket details',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 14,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 12),
        ],
        _DetailGrid(ticket: ticket),
        const SizedBox(height: 16),
        const Text(
          'Description',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 13,
            color: DesignTokens.ink,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          ticket.description.trim().isEmpty
              ? 'No additional description provided.'
              : ticket.description,
          style: const TextStyle(
            color: DesignTokens.ink,
            height: 1.45,
            fontSize: 13,
          ),
        ),
        if (ticket.attachments.isNotEmpty) ...[
          const SizedBox(height: 16),
          const Text(
            'Attachments',
            style: TextStyle(
              fontWeight: FontWeight.w800,
              fontSize: 13,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 8),
          ...ticket.attachments.map(
            (file) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: InkWell(
                onTap: () async {
                  try {
                    final result = await ApiClient.send(
                      method: 'GET',
                      url: '${AppConfig.resolvedApiBase}${file.downloadUrl}',
                      headers: AuthScope.of(context).ticketHeaders(),
                      asBytes: true,
                    );
                    if (!result.ok) {
                      throw StateError('Could not download file.');
                    }
                    await downloadBytesFile(
                      filename: file.originalFilename,
                      bytes: result.bytes,
                    );
                  } catch (error) {
                    if (!context.mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        behavior: SnackBarBehavior.floating,
                        backgroundColor: const Color(0xFF991B1B),
                        content: Text(_friendlyError(error)),
                      ),
                    );
                  }
                },
                child: Row(
                  children: [
                    const Icon(
                      Icons.attach_file_rounded,
                      size: 18,
                      color: DesignTokens.maroon,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        file.originalFilename,
                        style: const TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w700,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ],
    );

    if (embed) return content;
    return StudentPanel(
      shadow: false,
      padding: const EdgeInsets.all(16),
      child: SingleChildScrollView(child: content),
    );
  }
}

class _TicketReplyComposer extends StatelessWidget {
  final TextEditingController controller;
  final bool sending;
  final bool attaching;
  final String? error;
  final VoidCallback onSend;
  final VoidCallback onAttachImage;
  final VoidCallback onAttachFile;

  const _TicketReplyComposer({
    super.key,
    required this.controller,
    required this.sending,
    required this.attaching,
    required this.error,
    required this.onSend,
    required this.onAttachImage,
    required this.onAttachFile,
  });

  @override
  Widget build(BuildContext context) {
    final busy = sending || attaching;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: DesignTokens.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          TextField(
            controller: controller,
            minLines:
                MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint
                    ? 1
                    : 2,
            maxLines:
                MediaQuery.sizeOf(context).width < kPhoneLayoutBreakpoint
                    ? 3
                    : 4,
            enabled: !busy,
            textInputAction: TextInputAction.newline,
            decoration: InputDecoration(
              hintText: 'Write a reply to the office…',
              filled: true,
              fillColor: const Color(0xFFF8FAFC),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: DesignTokens.border),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: const BorderSide(color: DesignTokens.border),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(
                  color: DesignTokens.ink.withValues(alpha: 0.35),
                ),
              ),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 14,
                vertical: 12,
              ),
            ),
          ),
          if (error != null) ...[
            const SizedBox(height: 8),
            Text(
              error!,
              style: const TextStyle(
                color: Color(0xFFB91C1C),
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ],
          if (attaching) ...[
            const SizedBox(height: 8),
            const Text(
              'Uploading attachment…',
              style: TextStyle(
                color: DesignTokens.muted,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              IconButton(
                tooltip: 'Attach image',
                onPressed: busy ? null : onAttachImage,
                icon: const Icon(Icons.image),
                color: DesignTokens.maroon,
              ),
              IconButton(
                tooltip: 'Attach PDF or image',
                onPressed: busy ? null : onAttachFile,
                icon: const Icon(Icons.attach_file),
                color: DesignTokens.maroon,
              ),
              const Spacer(),
              ElevatedButton.icon(
                onPressed: busy ? null : onSend,
                icon:
                    sending
                        ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                        : const Icon(Icons.send_rounded, size: 18),
                label: Text(sending ? 'Sending…' : 'Send reply'),
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 12,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TicketStatusBanner extends StatelessWidget {
  final String status;

  const _TicketStatusBanner({required this.status});

  @override
  Widget build(BuildContext context) {
    final isClosed = status == 'Closed';
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFECFDF5),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFF86EFAC)),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.check_circle_outline_rounded,
            color: Color(0xFF16A34A),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              isClosed
                  ? 'This ticket has been closed.'
                  : 'This ticket has been marked as resolved.',
              style: const TextStyle(
                color: Color(0xFF166534),
                fontWeight: FontWeight.w900,
                height: 1.3,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DialogSectionHeader extends StatelessWidget {
  final String title;
  final String? trailing;

  const _DialogSectionHeader({required this.title, this.trailing});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: const TextStyle(
              fontWeight: FontWeight.w900,
              color: DesignTokens.ink,
              fontSize: 15,
            ),
          ),
        ),
        if (trailing != null)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: DesignTokens.maroon.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: DesignTokens.maroon.withValues(alpha: 0.14),
              ),
            ),
            child: Text(
              trailing!,
              style: const TextStyle(
                color: DesignTokens.maroon,
                fontWeight: FontWeight.w900,
                fontSize: 11,
              ),
            ),
          ),
      ],
    );
  }
}

class _DetailGrid extends StatelessWidget {
  final TicketEntry ticket;

  const _DetailGrid({required this.ticket});

  @override
  Widget build(BuildContext context) {
    final details = [
      _DetailData('Category', ticket.category, Icons.category_outlined),
      _DetailData(
        'Assigned office',
        ticket.assignedOffice,
        Icons.apartment_rounded,
      ),
      _DetailData(
        'Created',
        _formatFullDate(ticket.createdAt),
        Icons.event_available_outlined,
      ),
      _DetailData(
        'Updated',
        _formatFullDate(ticket.updatedAt),
        Icons.update_rounded,
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 620 ? 2 : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: 12,
          children:
              details
                  .map(
                    (detail) => Container(
                      padding: const EdgeInsets.all(14),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(color: DesignTokens.border),
                      ),
                      child: Row(
                        children: [
                          StudentIconBox(
                            icon: detail.icon,
                            color: DesignTokens.maroon,
                            size: 34,
                          ),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  detail.label,
                                  style: const TextStyle(
                                    color: DesignTokens.muted,
                                    fontSize: 12,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                                const SizedBox(height: 3),
                                Text(
                                  detail.value,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    color: DesignTokens.ink,
                                    fontWeight: FontWeight.w800,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  )
                  .toList(),
        );
      },
    );
  }
}

class _DetailData {
  final String label;
  final String value;
  final IconData icon;

  const _DetailData(this.label, this.value, this.icon);
}

class ConversationTimeline extends StatelessWidget {
  final TicketEntry ticket;
  final ScrollController? scrollController;
  final Future<void> Function(_TicketAttachment file)? onDownloadAttachment;

  const ConversationTimeline({
    super.key,
    required this.ticket,
    this.scrollController,
    this.onDownloadAttachment,
  });

  @override
  Widget build(BuildContext context) {
    final replies = ticket.messages;
    final children = <Widget>[
      StudentConcernBubble(ticket: ticket),
      const SizedBox(height: 14),
      if (replies.isEmpty)
        const _NoOfficeRepliesState()
      else
        ...replies.map(
          (message) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child:
                message.senderRole.toLowerCase() == 'student'
                    ? _StudentReplyBubble(message: message)
                    : OfficeReplyBubble(message: message),
          ),
        ),
      if (ticket.attachments.isNotEmpty) ...[
        const SizedBox(height: 8),
        const Text(
          'Attachments',
          style: TextStyle(
            fontWeight: FontWeight.w800,
            fontSize: 13,
            color: DesignTokens.ink,
          ),
        ),
        const SizedBox(height: 8),
        ...ticket.attachments.map(
          (file) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Material(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(10),
              child: InkWell(
                onTap:
                    onDownloadAttachment == null
                        ? null
                        : () => onDownloadAttachment!(file),
                borderRadius: BorderRadius.circular(10),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 10,
                  ),
                  child: Row(
                    children: [
                      Icon(
                        file.isImage ? Icons.image : Icons.picture_as_pdf,
                        size: 18,
                        color: DesignTokens.maroon,
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          file.originalFilename,
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ),
                      const Text(
                        'Download',
                        style: TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ];

    if (scrollController != null) {
      return ListView(
        controller: scrollController,
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 18),
        children: children,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: children,
    );
  }
}

class _StudentReplyBubble extends StatelessWidget {
  final TicketMessage message;

  const _StudentReplyBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerRight,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 520),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: const Color(0xFFEFF6FF),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFFBFDBFE)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'You · ${_formatDate(message.createdAt)}',
              style: const TextStyle(
                color: Color(0xFF1D4ED8),
                fontWeight: FontWeight.w800,
                fontSize: 12,
              ),
            ),
            const SizedBox(height: 6),
            _TicketFormattedText(message.message),
          ],
        ),
      ),
    );
  }
}

class StudentConcernBubble extends StatelessWidget {
  final TicketEntry ticket;

  const StudentConcernBubble({super.key, required this.ticket});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFD7DEE9)),
        boxShadow: DesignTokens.softShadow(0.035),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: const Color(0xFFE2E8F0),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(
                  Icons.person_outline_rounded,
                  color: DesignTokens.muted,
                  size: 19,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      ticket.userName.trim().isEmpty
                          ? 'Student concern'
                          : ticket.userName,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: DesignTokens.ink,
                        fontWeight: FontWeight.w900,
                        fontSize: 13,
                      ),
                    ),
                    const Text(
                      'Student concern',
                      style: TextStyle(
                        color: DesignTokens.muted,
                        fontWeight: FontWeight.w800,
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              ),
              Text(
                _formatDate(ticket.createdAt),
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),
          Text(
            ticket.subject,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 15,
              height: 1.35,
            ),
          ),
          if (ticket.description.trim().isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              ticket.description,
              style: const TextStyle(color: DesignTokens.ink, height: 1.45),
            ),
          ],
        ],
      ),
    );
  }
}

class _NoOfficeRepliesState extends StatelessWidget {
  const _NoOfficeRepliesState();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.035),
      ),
      child: const Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StudentIconBox(
            icon: Icons.support_agent_rounded,
            color: DesignTokens.maroon,
            size: 38,
          ),
          SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'No office replies yet.',
                  style: TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w900,
                    fontSize: 14,
                  ),
                ),
                SizedBox(height: 4),
                Text(
                  'Your assigned office will respond here once they review your concern.',
                  style: TextStyle(
                    color: DesignTokens.muted,
                    height: 1.4,
                    fontWeight: FontWeight.w700,
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

class OfficeReplyBubble extends StatelessWidget {
  final TicketMessage message;

  const OfficeReplyBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 680),
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFFFFF7ED),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(
            color: DesignTokens.maroon.withValues(alpha: 0.24),
          ),
          boxShadow: DesignTokens.softShadow(0.045),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: DesignTokens.maroon.withValues(alpha: 0.10),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Icon(
                    Icons.support_agent_rounded,
                    color: DesignTokens.maroon,
                    size: 19,
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        message.senderName.trim().isEmpty
                            ? 'Assigned Office'
                            : message.senderName,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w900,
                          fontSize: 13,
                        ),
                      ),
                      const Text(
                        'Office Reply',
                        style: TextStyle(
                          color: DesignTokens.muted,
                          fontWeight: FontWeight.w800,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 9,
                    vertical: 5,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.72),
                    borderRadius: BorderRadius.circular(999),
                    border: Border.all(
                      color: DesignTokens.maroon.withValues(alpha: 0.10),
                    ),
                  ),
                  child: Text(
                    _formatDate(message.createdAt),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            _TicketFormattedText(message.message),
          ],
        ),
      ),
    );
  }
}

class MessageBubble extends StatelessWidget {
  final TicketMessage message;

  const MessageBubble({super.key, required this.message});

  @override
  Widget build(BuildContext context) {
    final isStudent = message.senderRole.toLowerCase() == 'student';
    final color = isStudent ? const Color(0xFFF8FAFC) : const Color(0xFFFFF7ED);
    final borderColor =
        isStudent ? DesignTokens.border : const Color(0xFFFED7AA);
    final accent = isStudent ? DesignTokens.muted : DesignTokens.maroon;

    return Align(
      alignment: isStudent ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 620),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: color,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: borderColor),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  isStudent
                      ? Icons.person_outline_rounded
                      : Icons.business_center_outlined,
                  color: accent,
                  size: 18,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '${message.senderName} • ${_titleCase(message.senderRole)}',
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: accent,
                      fontWeight: FontWeight.w900,
                      fontSize: 12,
                    ),
                  ),
                ),
                Text(
                  _formatDate(message.createdAt),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 9),
            _TicketFormattedText(message.message),
          ],
        ),
      ),
    );
  }
}

class _TicketFormattedText extends StatelessWidget {
  final String text;

  const _TicketFormattedText(this.text);

  @override
  Widget build(BuildContext context) {
    return Text.rich(
      TextSpan(
        style: const TextStyle(color: DesignTokens.ink, height: 1.45),
        children: _parseTicketFormattedSpans(text),
      ),
    );
  }
}

List<InlineSpan> _parseTicketFormattedSpans(String input) {
  if (input.isEmpty) return const [TextSpan(text: '')];
  final pattern = RegExp(r'\*\*(.+?)\*\*|_(.+?)_|<u>(.+?)</u>', dotAll: true);
  final spans = <InlineSpan>[];
  var start = 0;
  for (final match in pattern.allMatches(input)) {
    if (match.start > start) {
      spans.add(TextSpan(text: input.substring(start, match.start)));
    }
    if (match.group(1) != null) {
      spans.add(
        TextSpan(
          text: match.group(1),
          style: const TextStyle(fontWeight: FontWeight.w800),
        ),
      );
    } else if (match.group(2) != null) {
      spans.add(
        TextSpan(
          text: match.group(2),
          style: const TextStyle(fontStyle: FontStyle.italic),
        ),
      );
    } else if (match.group(3) != null) {
      spans.add(
        TextSpan(
          text: match.group(3),
          style: const TextStyle(decoration: TextDecoration.underline),
        ),
      );
    }
    start = match.end;
  }
  if (start < input.length) {
    spans.add(TextSpan(text: input.substring(start)));
  }
  return spans;
}

class TicketStatusChip extends StatelessWidget {
  final String status;

  const TicketStatusChip({super.key, required this.status});

  @override
  Widget build(BuildContext context) {
    final style = _statusStyle(status);
    return _ChipPill(label: status, color: style.color);
  }
}

class TicketPriorityChip extends StatelessWidget {
  final String priority;

  const TicketPriorityChip({super.key, required this.priority});

  @override
  Widget build(BuildContext context) {
    final style = _priorityStyle(priority);
    return _ChipPill(label: priority, color: style.color);
  }
}

/// Compact text-only status/priority pill -- the redesign removes the
/// decorative per-status icon that used to sit inside this chip; color
/// alone (from [_ChipStyle]) still carries the at-a-glance meaning.
class _ChipPill extends StatelessWidget {
  final String label;
  final Color color;

  const _ChipPill({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withOpacity(0.18)),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w900,
          color: color,
        ),
      ),
    );
  }
}

class TicketEmptyState extends StatelessWidget {
  final String title;
  final String message;
  // Only set for the genuinely-empty ("No tickets yet") state -- a clear
  // path to submitting a first ticket right where the empty message is,
  // not just the summary row's own Submit Ticket button further up the
  // page.
  final VoidCallback? onSubmitTicket;

  const TicketEmptyState({
    super.key,
    required this.title,
    required this.message,
    this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 42),
      shadow: false,
      child: Column(
        children: [
          Text(
            title,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w900,
              fontSize: 18,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: DesignTokens.muted, height: 1.35),
          ),
          if (onSubmitTicket != null) ...[
            const SizedBox(height: 18),
            ElevatedButton(
              onPressed: onSubmitTicket,
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                elevation: 0,
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 13,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                ),
              ),
              child: const Text(
                'Submit a Ticket',
                style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class TicketLoadingState extends StatelessWidget {
  const TicketLoadingState({super.key});

  @override
  Widget build(BuildContext context) {
    return const StudentPanel(
      padding: EdgeInsets.symmetric(vertical: 44),
      shadow: false,
      child: Center(
        child: CircularProgressIndicator(color: DesignTokens.maroon),
      ),
    );
  }
}

class _TicketError extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _TicketError({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 13, color: Color(0xFF9A3412)),
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}

class CreateTicketForm extends StatefulWidget {
  final String? initialQuestion;
  final ValueChanged<TicketEntry> onCreated;
  final bool compact;

  /// Seeded offices skip the network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugOffices;

  const CreateTicketForm({
    super.key,
    this.initialQuestion,
    required this.onCreated,
    this.compact = false,
    this.debugOffices,
  });

  @override
  State<CreateTicketForm> createState() => _CreateTicketFormState();
}

class _CreateTicketFormState extends State<CreateTicketForm> {
  final _formKey = GlobalKey<FormState>();
  final TextEditingController _subjectCtrl = TextEditingController();
  final TextEditingController _descCtrl = TextEditingController();
  bool _submitting = false;
  PickedAppFile? _attachmentFile;
  String? _attachmentName;

  // Student direct office selection (additive; null = Automatic Routing,
  // the default and unchanged existing behavior -- see _submit()).
  List<_TicketOfficeOption> _offices = const [];
  bool _officesLoading = true;
  String? _selectedOfficeId;
  bool _officesRequested = false;

  @override
  void initState() {
    super.initState();
    _subjectCtrl.text = widget.initialQuestion ?? '';
    final seeded = widget.debugOffices;
    if (seeded != null) {
      _officesRequested = true;
      _officesLoading = false;
      _offices =
          seeded
              .map(
                (item) => _TicketOfficeOption(
                  id: (item['id'] ?? '').toString(),
                  name: (item['name'] ?? '').toString(),
                ),
              )
              .where((office) => office.id.isNotEmpty && office.name.isNotEmpty)
              .toList();
    }
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    // AuthScope.of(context) needs the inherited-widget chain to be attached,
    // which is only guaranteed from here on, not in initState().
    if (!_officesRequested) {
      _officesRequested = true;
      _loadOffices();
    }
  }

  Future<void> _loadOffices() async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/offices',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (result.statusCode < 200 || result.statusCode >= 300) return;
      final data = _decodeObject(result.body);
      final items = data['items'];
      if (items is! List) return;
      if (!mounted) return;
      setState(() {
        _offices =
            items
                .whereType<Map>()
                .map(
                  (item) => _TicketOfficeOption(
                    id: (item['id'] ?? '').toString(),
                    name: (item['name'] ?? '').toString(),
                  ),
                )
                .where(
                  (office) => office.id.isNotEmpty && office.name.isNotEmpty,
                )
                .toList();
      });
    } catch (_) {
      // Office list is a nice-to-have for manual selection only -- Automatic
      // Routing (the default) must remain fully usable even if this fails.
    } finally {
      if (mounted) setState(() => _officesLoading = false);
    }
  }

  @override
  void dispose() {
    _subjectCtrl.dispose();
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickAttachment() async {
    final picked = await pickAppFile(
      allowedExtensions: const [
        'pdf',
        'png',
        'jpg',
        'jpeg',
        'webp',
        'gif',
        'bmp',
        'heic',
        'tif',
        'tiff',
      ],
      dialogTitle: 'Select an attachment',
    );
    if (picked == null) return;
    if (picked.bytes.length > 10 * 1024 * 1024) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: Color(0xFF991B1B),
          content: Text('Attachment must be 10 MB or smaller.'),
        ),
      );
      return;
    }
    setState(() {
      _attachmentFile = picked;
      _attachmentName = picked.name;
    });
  }

  Future<void> _uploadAttachment(String ticketId) async {
    final file = _attachmentFile;
    if (file == null) return;
    final result = await ApiClient.multipart(
      method: 'POST',
      url: '${AppConfig.resolvedApiBase}/tickets/$ticketId/attachments',
      headers: AuthScope.of(context).ticketHeaders(),
      files: [
        http.MultipartFile.fromBytes('file', file.bytes, filename: file.name),
      ],
    );
    final statusCode = result.statusCode;
    if (statusCode < 200 || statusCode >= 300) {
      final data = _decodeObject(result.body);
      throw StateError(_extractError(data, 'Attachment upload failed.'));
    }
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _submitting = true);
    try {
      final body = <String, dynamic>{
        'original_question': _subjectCtrl.text.trim(),
        'description': _descCtrl.text.trim(),
        'source_from_chatbot': widget.initialQuestion != null,
      };
      // Automatic Routing (the default, _selectedOfficeId == null) must
      // never send these fields -- ticket behavior is then identical to
      // today's existing automatic pipeline.
      if (_selectedOfficeId != null) {
        body['routing_method'] = 'student_selected';
        body['preferred_office_id'] = _selectedOfficeId;
      }
      final result = await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: body,
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw StateError(_extractError(data, 'Ticket submission failed.'));
      }
      var ticket = TicketEntry.fromJson(data);
      if (_attachmentFile != null) {
        await _uploadAttachment(ticket.id);
        final refresh = await ApiClient.send(
          method: 'GET',
          url: '${AppConfig.resolvedApiBase}/tickets/${ticket.id}',
          headers: AuthScope.of(context).ticketHeaders(),
        );
        final refreshed = _decodeObject(refresh.body);
        if (refresh.statusCode >= 200 && refresh.statusCode < 300) {
          ticket = TicketEntry.fromJson(refreshed);
        }
      }
      widget.onCreated(ticket);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('Ticket submitted successfully.'),
        ),
      );
      setState(() {
        _subjectCtrl.clear();
        _descCtrl.clear();
        _attachmentFile = null;
        _attachmentName = null;
        _selectedOfficeId = null;
      });
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          behavior: SnackBarBehavior.floating,
          backgroundColor: const Color(0xFF991B1B),
          content: Text(_friendlyError(error)),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _submitting = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    // Compact (phone): tighter gaps between fields/sections -- the field
    // labels/placeholders themselves are now the same at every width (no
    // numbered badges, no per-field explainer paragraphs, short/no
    // placeholders), matching the HESK reference's plain label+input
    // style rather than treating mobile as a stripped-down version of a
    // more verbose desktop form.
    final fieldGap = widget.compact ? 12.0 : 18.0;
    final labelGap = widget.compact ? 4.0 : 6.0;
    final form = Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _FieldLabel(label: 'Office (optional)'),
          SizedBox(height: labelGap),
          DropdownButtonFormField<String?>(
            value: _selectedOfficeId,
            isExpanded: true,
            // Same subtle rose "this is set" cue as My Tickets' own
            // filter dropdowns -- active once a specific office is
            // picked instead of automatic routing.
            decoration: _inputDecoration(
              hintText: 'Automatic routing — Let ASKa-Piyu choose',
            ).copyWith(
              fillColor:
                  _selectedOfficeId != null ? const Color(0xFFFBF2F3) : null,
              enabledBorder:
                  _selectedOfficeId != null
                      ? OutlineInputBorder(
                        borderRadius: BorderRadius.circular(14),
                        borderSide: BorderSide(
                          color: DesignTokens.maroon.withValues(alpha: 0.35),
                        ),
                      )
                      : null,
            ),
            items: [
              const DropdownMenuItem<String?>(
                value: null,
                child: Text('Automatic routing — Let ASKa-Piyu choose'),
              ),
              ..._offices.map(
                (office) => DropdownMenuItem<String?>(
                  value: office.id,
                  child: Text(office.name),
                ),
              ),
            ],
            onChanged:
                _officesLoading && _offices.isEmpty
                    ? null
                    : (value) => setState(() => _selectedOfficeId = value),
          ),
          SizedBox(height: fieldGap),
          const _FieldLabel(label: 'Subject'),
          SizedBox(height: labelGap),
          TextFormField(
            controller: _subjectCtrl,
            validator: _validateTicketSubject,
            textInputAction: TextInputAction.next,
            decoration: _inputDecoration(),
          ),
          SizedBox(height: fieldGap),
          const _FieldLabel(label: 'Description'),
          SizedBox(height: labelGap),
          TextFormField(
            controller: _descCtrl,
            validator: _validateTicketDescription,
            minLines: widget.compact ? 4 : 5,
            maxLines: widget.compact ? 6 : 7,
            decoration: _inputDecoration(hintText: 'Describe your concern'),
          ),
          SizedBox(height: fieldGap),
          _FieldLabel(
            label: 'Attachment (optional)',
            helper: '$_attachmentFormatsLabel — max 10 MB.',
          ),
          SizedBox(height: labelGap),
          _AttachmentPicker(
            fileName: _attachmentName,
            onPick: _submitting ? null : _pickAttachment,
            onClear:
                _submitting || _attachmentName == null
                    ? null
                    : () => setState(() {
                      _attachmentFile = null;
                      _attachmentName = null;
                    }),
          ),
          SizedBox(height: widget.compact ? 14 : 20),
          LayoutBuilder(
            builder: (context, constraints) {
              final isNarrow = constraints.maxWidth < 420;
              final clearButton = OutlinedButton(
                onPressed:
                    _submitting
                        ? null
                        : () {
                          _subjectCtrl.clear();
                          _descCtrl.clear();
                          setState(() {
                            _attachmentFile = null;
                            _attachmentName = null;
                            _selectedOfficeId = null;
                          });
                        },
                style: OutlinedButton.styleFrom(
                  foregroundColor: DesignTokens.ink,
                  side: const BorderSide(color: DesignTokens.border),
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 15,
                  ),
                ),
                child: const Text('Clear'),
              );
              final submitButton = ElevatedButton(
                onPressed: _submitting ? null : _submit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.maroon,
                  foregroundColor: Colors.white,
                  elevation: 0,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 22,
                    vertical: 15,
                  ),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                ),
                child:
                    _submitting
                        ? const Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            ),
                            SizedBox(width: 10),
                            Text('Submitting...'),
                          ],
                        )
                        : const Text('Submit Ticket'),
              );

              if (isNarrow) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    submitButton,
                    const SizedBox(height: 10),
                    clearButton,
                  ],
                );
              }

              return Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  clearButton,
                  const SizedBox(width: 12),
                  submitButton,
                ],
              );
            },
          ),
        ],
      ),
    );

    const guidance = _SubmitTicketGuidance();

    // The form card and the guidance column are deliberately two independent
    // pieces of composition, not one shared bordered container -- wrapping
    // both in a single StudentPanel made the right column's white background
    // stretch down to match the (much taller) form, leaving a huge empty
    // bordered region below it. The guidance column's own card already
    // carries its own border/background, so it needs no outer panel at
    // all; it simply sizes to its content.
    final formCard = StudentPanel(
      padding:
          widget.compact
              ? const EdgeInsets.fromLTRB(14, 14, 14, 14)
              : const EdgeInsets.fromLTRB(24, 24, 22, 22),
      child: form,
    );

    return LayoutBuilder(
      builder: (context, constraints) {
        if (constraints.maxWidth >= 760) {
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 7, child: formCard),
              const SizedBox(width: 24),
              Expanded(flex: 3, child: guidance),
            ],
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [formCard, const SizedBox(height: 20), guidance],
        );
      },
    );
  }
}

/// The real, accurate list of file types [pickAppFile] accepts for ticket
/// attachments (see [_CreateTicketFormState._pickAttachment]) -- kept as a
/// single source of truth for the Attachment field's own helper text.
const _attachmentFormatsLabel =
    'JPG, JPEG, PNG, WebP, GIF, BMP, HEIC, TIFF, or PDF';

/// Right-side (desktop) / below-form (narrow) guidance column for the
/// Submit Ticket view. Just the "Before submitting" tips card -- the
/// separate "File requirements" card that used to sit below it was
/// redundant with the Attachment field's own helper text (format list +
/// 10 MB limit), which already covers this, so it was removed rather
/// than duplicated.
class _SubmitTicketGuidance extends StatelessWidget {
  const _SubmitTicketGuidance();

  static const _tips = [
    'Provide a clear and specific subject',
    'Include important details such as dates or reference numbers',
    'Attach relevant screenshots or documents',
    'Choose the correct office if you know it',
    "Use Automatic Routing if you're not sure",
  ];

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFFFBF2F3),
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE8B4B8)),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Before submitting',
                style: TextStyle(
                  color: DesignTokens.maroon,
                  fontWeight: FontWeight.w900,
                  fontSize: 15,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Providing clear and complete details helps the office '
                'respond faster.',
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 12.5,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 14),
              const Divider(height: 1, color: Color(0xFFE8B4B8)),
              const SizedBox(height: 14),
              const Text(
                'Tips for a faster response',
                style: TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 8),
              for (var i = 0; i < _tips.length; i++)
                Padding(
                  padding: EdgeInsets.only(
                    bottom: i == _tips.length - 1 ? 0 : 8,
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      SizedBox(
                        width: 18,
                        child: Text(
                          '${i + 1}',
                          style: const TextStyle(
                            color: DesignTokens.maroon,
                            fontWeight: FontWeight.w900,
                            fontSize: 12.5,
                          ),
                        ),
                      ),
                      Expanded(
                        child: Text(
                          _tips[i],
                          style: const TextStyle(
                            color: DesignTokens.muted,
                            fontSize: 12.5,
                            height: 1.4,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _TicketOfficeOption {
  final String id;
  final String name;

  const _TicketOfficeOption({required this.id, required this.name});
}

/// A simple field label -- optionally with one short, essential line
/// beneath it (used only by Attachment, for its file-type/size limit).
/// No numbered marker: the Submit Ticket form reads as a plain list of
/// labeled fields now, not a sequence of numbered steps.
class _FieldLabel extends StatelessWidget {
  final String label;
  final String? helper;

  const _FieldLabel({required this.label, this.helper});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontWeight: FontWeight.w900,
          ),
        ),
        if (helper != null && helper!.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            helper!,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              height: 1.35,
            ),
          ),
        ],
      ],
    );
  }
}

/// Click-to-select attachment picker. The application only ever supports
/// a native file picker dialog (no drag-and-drop), so the wording here
/// stays accurate to that -- "Choose a file", never drag-and-drop copy.
class _AttachmentPicker extends StatelessWidget {
  final String? fileName;
  final VoidCallback? onPick;
  final VoidCallback? onClear;

  const _AttachmentPicker({
    required this.fileName,
    required this.onPick,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    final hasFile = fileName != null && fileName!.isNotEmpty;
    return InkWell(
      onTap: onPick,
      borderRadius: BorderRadius.circular(14),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        decoration: BoxDecoration(
          color: const Color(0xFFFBF2F3),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: DesignTokens.border),
        ),
        child:
            hasFile
                ? Row(
                  children: [
                    Expanded(
                      child: Text(
                        fileName!,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: DesignTokens.ink,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                    if (onClear != null)
                      TextButton(
                        onPressed: onClear,
                        child: const Text('Remove'),
                      ),
                    TextButton(onPressed: onPick, child: const Text('Change')),
                  ],
                )
                : Column(
                  children: [
                    const Text(
                      'Choose a file',
                      style: TextStyle(
                        color: DesignTokens.maroon,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'No file selected',
                      style: TextStyle(color: DesignTokens.muted, fontSize: 12),
                    ),
                  ],
                ),
      ),
    );
  }
}


class _ChipStyle {
  final Color color;

  const _ChipStyle(this.color);
}

InputDecoration _inputDecoration({String? hintText}) {
  return InputDecoration(
    hintText: hintText,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(14),
      borderSide: BorderSide(
        color: DesignTokens.ink.withValues(alpha: 0.35),
        width: 1.2,
      ),
    ),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
  );
}

_ChipStyle _statusStyle(String status) {
  switch (status) {
    case 'Open':
      return const _ChipStyle(Color(0xFF2563EB));
    case 'In Progress':
      return const _ChipStyle(Color(0xFFF97316));
    case 'Resolved':
      return const _ChipStyle(Color(0xFF7C3AED));
    case 'Closed':
      return const _ChipStyle(Color(0xFF16A34A));
    default:
      return const _ChipStyle(DesignTokens.muted);
  }
}

_ChipStyle _priorityStyle(String priority) {
  switch (priority) {
    case 'Urgent':
      return const _ChipStyle(Color(0xFFDC2626));
    case 'High':
      return const _ChipStyle(Color(0xFFEA580C));
    case 'Medium':
      return const _ChipStyle(Color(0xFFD97706));
    case 'Low':
      return const _ChipStyle(Color(0xFF0F766E));
    default:
      return const _ChipStyle(DesignTokens.muted);
  }
}

Map<String, dynamic> _decodeObject(String? responseText) {
  final text = (responseText ?? '').trim();
  if (text.isEmpty) return <String, dynamic>{};
  try {
    final decoded = jsonDecode(text);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
  } catch (_) {
    return <String, dynamic>{'detail': text};
  }
}

int _readInt(Object? value) {
  if (value is int) return value;
  if (value is num) return value.toInt();
  return int.tryParse('$value') ?? 0;
}

class _TicketAttachment {
  final String id;
  final String ticketId;
  final String originalFilename;
  final String contentType;
  final int sizeBytes;
  final String downloadUrl;

  const _TicketAttachment({
    required this.id,
    required this.ticketId,
    required this.originalFilename,
    required this.contentType,
    required this.sizeBytes,
    required this.downloadUrl,
  });

  factory _TicketAttachment.fromJson(Map<String, dynamic> json) {
    return _TicketAttachment(
      id: (json['id'] ?? '').toString(),
      ticketId: (json['ticket_id'] ?? '').toString(),
      originalFilename: (json['original_filename'] ?? 'file').toString(),
      contentType: (json['content_type'] ?? '').toString(),
      sizeBytes: _readInt(json['size_bytes']),
      downloadUrl: (json['download_url'] ?? '').toString(),
    );
  }

  bool get isImage => contentType.toLowerCase().startsWith('image/');
}

String _extractError(Map<String, dynamic> data, String fallback) {
  final detail = data['detail'];
  if (detail is String && detail.trim().isNotEmpty) return detail;
  if (detail is List && detail.isNotEmpty) {
    return detail.map((item) => item.toString()).join('\n');
  }
  final message = data['message'];
  if (message is String && message.trim().isNotEmpty) return message;
  return fallback;
}

String _friendlyError(Object error) {
  final text = error.toString().replaceFirst('Bad state: ', '').trim();
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}

DateTime _parseDate(Object? value) {
  return _parseNullableDate(value) ?? DateTime.now();
}

DateTime? _parseNullableDate(Object? value) {
  final text = value?.toString().trim() ?? '';
  if (text.isEmpty || text == 'null') return null;
  return DateTime.tryParse(text)?.toLocal();
}

double? _parseDouble(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}

String? _nullableString(Object? value) {
  final text = value?.toString().trim() ?? '';
  return text.isEmpty || text == 'null' ? null : text;
}

String? _validateTicketSubject(String? value) {
  final cleaned = (value ?? '').trim().replaceAll(RegExp(r'\s+'), ' ');
  if (cleaned.length < 8) {
    return 'Subject must be at least 8 characters.';
  }
  final words = RegExp(r"[A-Za-zÀ-ÿ]{2,}").allMatches(cleaned).toList();
  if (words.length < 2) {
    return 'Use at least two real words in the subject.';
  }
  return _unreadableTicketTextMessage(
    cleaned,
    words.map((m) => m.group(0)!).toList(),
    minLetters: 6,
  );
}

String? _validateTicketDescription(String? value) {
  final cleaned = (value ?? '').trim().replaceAll(RegExp(r'\s+'), ' ');
  if (cleaned.length < 20) {
    return 'Description must be at least 20 characters. Add dates, steps tried, or what you need.';
  }
  final words = RegExp(r"[A-Za-zÀ-ÿ]{2,}").allMatches(cleaned).toList();
  if (words.length < 4) {
    return 'Use at least four real words so the office has enough context.';
  }
  return _unreadableTicketTextMessage(
    cleaned,
    words.map((m) => m.group(0)!).toList(),
    minLetters: 10,
  );
}

String? _unreadableTicketTextMessage(
  String cleaned,
  List<String> words, {
  int minLetters = 10,
}) {
  final letters =
      cleaned
          .toLowerCase()
          .split('')
          .where((ch) => RegExp(r'[a-zà-ÿ]').hasMatch(ch))
          .toList();
  if (letters.length < minLetters) {
    return 'Please write a clearer message in plain language.';
  }
  const vowels = 'aeiouáéíóúäëïöüàèìòùâêîôû';
  final vowelCount = letters.where((ch) => vowels.contains(ch)).length;
  final vowelRatio = vowelCount / letters.length;
  if (vowelRatio < 0.18 || vowelRatio > 0.72) {
    return 'This does not look like readable text. Please rewrite it in plain language.';
  }
  for (final word in words) {
    if (word.length < 10) continue;
    final wordLetters = word.toLowerCase().split('');
    final wordVowels = wordLetters.where((ch) => vowels.contains(ch)).length;
    if (wordVowels / wordLetters.length < 0.2) {
      return 'This contains unreadable text. Please rewrite it in plain language.';
    }
  }
  if (RegExp(
    r'[bcdfghjklmnpqrstvwxyz]{6,}',
    caseSensitive: false,
  ).hasMatch(cleaned)) {
    return 'This contains unreadable text. Please rewrite it in plain language.';
  }
  final lowered = cleaned.toLowerCase();
  for (final ch in lowered.split('').toSet()) {
    if (RegExp(r'[a-zà-ÿ]').hasMatch(ch) && lowered.contains(ch * 5)) {
      return 'This contains unreadable text. Please rewrite it in plain language.';
    }
  }
  return null;
}

String _titleStatus(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'in_progress' || normalized == 'in progress') {
    return 'In Progress';
  }
  if (normalized == 'resolved') return 'Resolved';
  if (normalized == 'closed') return 'Closed';
  return 'Open';
}

String _titlePriority(String value) {
  final normalized = value.trim().toLowerCase();
  if (normalized == 'urgent') return 'Urgent';
  if (normalized == 'high') return 'High';
  if (normalized == 'medium') return 'Medium';
  return 'Low';
}

String _titleCase(String value) {
  final text = value.trim();
  if (text.isEmpty) return '';
  return text[0].toUpperCase() + text.substring(1).toLowerCase();
}

String _formatDate(DateTime date) {
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  final hour = date.hour % 12 == 0 ? 12 : date.hour % 12;
  final minute = date.minute.toString().padLeft(2, '0');
  final ampm = date.hour >= 12 ? 'PM' : 'AM';
  return '${months[date.month - 1]} ${date.day}, $hour:$minute $ampm';
}

String _formatFullDate(DateTime date) {
  return '${_formatDate(date)}, ${date.year}';
}
