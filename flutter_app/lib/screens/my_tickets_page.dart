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
  final List<_TicketNotification> _notifications = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  String _statusFilter = 'All';
  String _officeFilter = 'All Offices';
  String _categoryFilter = 'All Categories';
  bool _requestedInitialLoad = false;
  int _unreadNotifications = 0;
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
    _listPollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (!mounted || !AuthScope.of(context).isAuthenticated) return;
      if (_tabController.index != 0) return;
      _loadTickets(silent: true);
      _loadNotifications(silent: true);
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
          _loadNotifications();
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

  Future<void> _loadNotifications({bool silent = false}) async {
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      final statusCode = result.statusCode;
      if (statusCode < 200 || statusCode >= 300) return;
      final items = data['items'] is List ? data['items'] as List : const [];
      if (!mounted) return;
      setState(() {
        _notifications
          ..clear()
          ..addAll(
            items.whereType<Map>().map(
              (item) =>
                  _TicketNotification.fromJson(Map<String, dynamic>.from(item)),
            ),
          );
        _unreadNotifications = _readInt(data['unread_count']);
      });
    } catch (_) {
      // Non-blocking: ticket list still works without notifications.
    }
  }

  Future<void> _markAllNotificationsRead() async {
    try {
      await ApiClient.send(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications/read-all',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      await _loadNotifications();
    } catch (_) {}
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
        final filteredTickets =
            _tickets
                .where(
                  (ticket) => ticket.matches(
                    _searchCtrl.text,
                    _statusFilter,
                    officeFilter: _officeFilter,
                    categoryFilter: _categoryFilter,
                  ),
                )
                .toList();
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
            await _loadNotifications();
          },
          color: DesignTokens.maroon,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_unreadNotifications > 0) ...[
                  _NotificationsBanner(
                    notifications:
                        _notifications
                            .where((item) => !item.isRead)
                            .take(3)
                            .toList(),
                    unreadCount: _unreadNotifications,
                    onDismiss: _markAllNotificationsRead,
                  ),
                  SizedBox(height: isWide ? 16 : 12),
                ],
                _TicketStatsSummary(
                  tickets: _tickets,
                  isWide: isWide,
                  onSubmitTicket: () => _tabController.animateTo(1),
                ),
                SizedBox(height: isWide ? 18 : 14),
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
              // Neither tab shows a "Back to ..." row above the hero -- the
              // navbar's own My Tickets nav item (kept active on both tabs)
              // already provides navigation, matching both approved targets.
              _TicketsHeroBanner(
                tabController: _tabController,
                isWide: isWide,
                isFaculty: AuthScope.of(context).role == 'faculty',
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

/// Shared hero banner for the My Tickets / Submit Ticket experience --
/// carries the same restrained light-maroon/pink wave language as the
/// approved homepage hero (a soft gradient with a single gentle curved
/// edge), without literally reusing the homepage's own multi-layer wave
/// painter. Reacts to [tabController] so the eyebrow/heading/subtitle swap
/// between the list and submit views instead of each view rendering its
/// own separate header.
class _TicketsHeroBanner extends StatelessWidget {
  final TabController tabController;
  final bool isWide;
  final bool isFaculty;

  const _TicketsHeroBanner({
    required this.tabController,
    required this.isWide,
    required this.isFaculty,
  });

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: tabController,
      builder: (context, _) {
        final onSubmitView = tabController.index == 1;
        final eyebrow = onSubmitView ? 'SUBMIT TICKET' : 'TICKETS';
        final title = onSubmitView ? 'Submit a Support Request' : 'My Tickets';
        final subtitle =
            onSubmitView
                ? 'Share your concern and any details the office will need to help you.'
                : isFaculty
                ? 'Create faculty support requests, track progress, and read office replies in one place.'
                : 'Create support requests, track progress, and read office replies in one place.';

        return ClipRect(
          child: Container(
            width: double.infinity,
            color: const Color(0xFFFDF1F2),
            child: Stack(
              children: [
                Positioned.fill(
                  child: IgnorePointer(
                    child: CustomPaint(painter: _TicketsHeroWavePainter()),
                  ),
                ),
                Padding(
                  padding: EdgeInsets.fromLTRB(
                    isWide ? 28 : 18,
                    isWide ? 26 : 20,
                    isWide ? 28 : 18,
                    isWide ? 46 : 34,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        eyebrow,
                        style: const TextStyle(
                          color: DesignTokens.maroon,
                          fontWeight: FontWeight.w800,
                          fontSize: 12,
                          letterSpacing: 1.4,
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        title,
                        style: TextStyle(
                          fontSize: isWide ? 37 : 24,
                          fontWeight: FontWeight.w900,
                          // Both hero titles share the same maroon
                          // treatment -- intentional visual consistency
                          // between My Tickets and Submit Ticket.
                          color: DesignTokens.maroon,
                          height: 1.05,
                        ),
                      ),
                      const SizedBox(height: 8),
                      ConstrainedBox(
                        constraints: BoxConstraints(
                          maxWidth: isWide ? 620 : 420,
                        ),
                        child: Text(
                          subtitle,
                          style: TextStyle(
                            fontSize: isWide ? 14 : 13,
                            color: DesignTokens.muted,
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
        );
      },
    );
  }
}

/// Wave shapes across the hero, rebuilt from pixel measurements of the
/// approved target screenshot (1672x941): a per-column scan for sustained
/// dusty-rose color found genuine wave presence only in the left ~14% and
/// right ~28% of the hero's width, with a wide, essentially flat/pale
/// middle band (x roughly 15%-70%) showing no sustained wave color at all.
/// That is a materially different silhouette from a single continuous
/// crest-and-valley: two independent, edge-anchored bands rather than one
/// wave spanning the full width. A soft top-to-bottom base tint (measured
/// going from ~(248,237,240) just below the navbar to ~(240,225,228) at
/// the hero's bottom edge, uniform across x) supplies the remaining depth
/// through that flat middle, standing in for the background gradient the
/// target shows there.
class _TicketsHeroWavePainter extends CustomPainter {
  const _TicketsHeroWavePainter();

  @override
  void paint(Canvas canvas, Size size) {
    // Uniform base gradient (not x-dependent): the measured middle band has
    // no distinct wave shape, just a gentle top-to-bottom deepening.
    canvas.drawRect(
      Offset.zero & size,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0xFFFDF1F2), Color(0xFFF6E1E4)],
        ).createShader(Offset.zero & size),
    );

    // Full-width soft wave: a single gentle S-curve visible across the whole
    // hero, at a light-enough tint that it doesn't register as "sustained
    // deep rose" in a strict per-column color scan (which is why the edge-
    // measurement below found the middle "empty") but still reads visually
    // as a continuous curved band, matching the target's overall softness.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFEFC3CA).withValues(alpha: 0.40),
      anchors: const [
        Offset(0.00, 0.40),
        Offset(0.25, 0.58),
        Offset(0.50, 0.76),
        Offset(0.75, 0.62),
        Offset(1.00, 0.50),
      ],
    );

    // Left band: measured sustained-rose top edge rises from ~49% of the
    // hero height at x=0 to ~90% (nearly gone) by x=~14%, then stays absent
    // through the wide middle.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFC17E88).withValues(alpha: 0.42),
      anchors: const [
        Offset(0.00, 0.49),
        Offset(0.05, 0.60),
        Offset(0.10, 0.74),
        Offset(0.15, 0.95),
      ],
    );

    // Right band: reappears around x=~72% (top edge ~90% down, i.e. barely
    // present) and thickens steadily toward the right edge (top edge ~55%
    // down at x=100%), the strongest/deepest point of the whole hero.
    _paintLayer(
      canvas,
      size,
      color: const Color(0xFFC17E88).withValues(alpha: 0.55),
      anchors: const [
        Offset(0.65, 0.98),
        Offset(0.72, 0.90),
        Offset(0.85, 0.75),
        Offset(1.00, 0.55),
      ],
    );
  }

  void _paintLayer(
    Canvas canvas,
    Size size, {
    required Color color,
    required List<Offset> anchors,
  }) {
    final pts = <Offset>[
      for (final a in anchors) Offset(size.width * a.dx, size.height * a.dy),
    ];
    final path =
        Path()
          ..moveTo(0, size.height)
          ..lineTo(pts.first.dx, pts.first.dy);
    for (var i = 0; i < pts.length - 1; i++) {
      final p0 = i == 0 ? pts[i] : pts[i - 1];
      final p1 = pts[i];
      final p2 = pts[i + 1];
      final p3 = (i + 2 < pts.length) ? pts[i + 2] : pts[i + 1];
      final c1 = p1 + (p2 - p0) / 6;
      final c2 = p2 - (p3 - p1) / 6;
      path.cubicTo(c1.dx, c1.dy, c2.dx, c2.dy, p2.dx, p2.dy);
    }
    path
      ..lineTo(size.width, size.height)
      ..close();
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _TicketsHeroWavePainter oldDelegate) => false;
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
/// The primary Submit Ticket action lives here (right side on desktop,
/// full-width below the stats on narrow layouts).
class _TicketStatsSummary extends StatelessWidget {
  final List<TicketEntry> tickets;
  final bool isWide;
  final VoidCallback onSubmitTicket;

  const _TicketStatsSummary({
    required this.tickets,
    required this.isWide,
    required this.onSubmitTicket,
  });

  @override
  Widget build(BuildContext context) {
    final openCount = tickets.where((t) => t.status == 'Open').length;
    final progressCount =
        tickets.where((t) => t.status == 'In Progress').length;
    final closedCount = tickets.where((t) => t.status == 'Closed').length;
    final totalCount = tickets.length;

    final blocks = [
      _StatBlock(
        number: '$openCount',
        label: 'Open',
        caption: 'Awaiting office response',
        color: const Color(0xFF2563EB),
      ),
      _StatBlock(
        number: '$progressCount',
        label: 'In Progress',
        caption: 'Being handled by the office',
        color: const Color(0xFFF97316),
      ),
      _StatBlock(
        number: '$closedCount',
        label: 'Closed',
        caption: 'Resolved tickets',
        color: const Color(0xFF16A34A),
      ),
      _StatBlock(
        number: '$totalCount',
        label: 'Total',
        caption: 'All time tickets',
        color: DesignTokens.maroon,
      ),
    ];

    final submitButton = SizedBox(
      height: 42,
      child: ElevatedButton(
        onPressed: onSubmitTicket,
        style: ElevatedButton.styleFrom(
          backgroundColor: DesignTokens.maroon,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 22),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: const Text(
          'Submit Ticket',
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
        ),
      ),
    );

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

    final narrowStatsGrid = LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth >= 380 ? 2 : 1;
        return StudentResponsiveWrap(
          columns: columns,
          spacing: 12,
          children: blocks,
        );
      },
    );

    return StudentPanel(
      padding: EdgeInsets.symmetric(
        horizontal: isWide ? 20 : 14,
        vertical: isWide ? 12 : 14,
      ),
      child:
          isWide
              ? Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Expanded(child: wideStatsRow),
                  const SizedBox(width: 22),
                  submitButton,
                ],
              )
              : Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  narrowStatsGrid,
                  const SizedBox(height: 14),
                  submitButton,
                ],
              ),
    );
  }
}

class _StatBlock extends StatelessWidget {
  final String number;
  final String label;
  final String caption;
  final Color color;

  const _StatBlock({
    required this.number,
    required this.label,
    required this.caption,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
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
              fontSize: 24,
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
            maxLines: 1,
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
class _TicketToolbar extends StatelessWidget {
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
            controller: searchCtrl,
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
            value: statusFilter,
            values: _statusOptions,
            displayValues: _statusOptionsDisplay,
            onChanged: onStatusChanged,
          );
          final officeDropdown = _FilterDropdown(
            label: 'All Offices',
            value: officeFilter,
            values: officeOptions,
            onChanged: onOfficeChanged,
          );
          final categoryDropdown = _FilterDropdown(
            label: 'All Categories',
            value: categoryFilter,
            values: categoryOptions,
            onChanged: onCategoryChanged,
          );
          final clearAction = TextButton(
            onPressed: hasActiveFilters ? onClear : null,
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
            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                searchField,
                const SizedBox(height: 12),
                statusDropdown,
                const SizedBox(height: 10),
                officeDropdown,
                const SizedBox(height: 10),
                categoryDropdown,
                const SizedBox(height: 10),
                Align(alignment: Alignment.centerRight, child: clearAction),
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
    return DropdownButtonFormField<String>(
      value: value,
      isExpanded: true,
      decoration: _inputDecoration(hintText: label).copyWith(
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 10,
        ),
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

  const TicketsList({
    super.key,
    required this.tickets,
    required this.hasAnyTickets,
    required this.onTicketTap,
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

/// Wide horizontal card matching the approved target: a left ID/date
/// column, a vertical divider, a main column (status/priority, subject,
/// office/category/replies, description preview), and a trailing chevron.
/// Stacks (ID+date above main) on narrower widths instead of overflowing.
class TicketCard extends StatelessWidget {
  final TicketEntry ticket;
  final VoidCallback onTap;

  const TicketCard({super.key, required this.ticket, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final idAndDate = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          ticket.id,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: DesignTokens.maroon,
            fontWeight: FontWeight.w900,
            fontSize: 14,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          _formatDate(ticket.updatedAt),
          style: const TextStyle(color: DesignTokens.muted, fontSize: 12.5),
        ),
      ],
    );

    final mainColumn = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            TicketStatusChip(status: ticket.status),
            TicketPriorityChip(priority: ticket.priority),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          ticket.subject,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontWeight: FontWeight.w900,
            fontSize: 17,
          ),
        ),
        const SizedBox(height: 8),
        _TicketMetaLine(
          parts: [
            ticket.assignedOffice,
            ticket.category,
            '${ticket.messages.length} '
                '${ticket.messages.length == 1 ? 'reply' : 'replies'}',
          ],
        ),
        if (ticket.description.trim().isNotEmpty) ...[
          const SizedBox(height: 10),
          Text(
            ticket.description,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 13,
              height: 1.35,
            ),
          ),
        ],
      ],
    );

    return StudentInkCard(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 15),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final isNarrow = constraints.maxWidth < 640;
          if (isNarrow) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: idAndDate),
                    const Icon(
                      Icons.chevron_right_rounded,
                      color: DesignTokens.muted,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                mainColumn,
              ],
            );
          }

          return IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(width: 180, child: idAndDate),
                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 18),
                  child: VerticalDivider(
                    width: 1,
                    thickness: 1,
                    color: DesignTokens.border,
                  ),
                ),
                Expanded(child: mainColumn),
                const SizedBox(width: 10),
                const Icon(
                  Icons.chevron_right_rounded,
                  color: DesignTokens.muted,
                ),
              ],
            ),
          );
        },
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

  const TicketEmptyState({
    super.key,
    required this.title,
    required this.message,
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
    final form = Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _FieldLabel(
            number: 1,
            label: 'Office (optional)',
            helper: 'Select the office you want to send this ticket to.',
          ),
          const SizedBox(height: 6),
          DropdownButtonFormField<String?>(
            value: _selectedOfficeId,
            isExpanded: true,
            decoration: _inputDecoration(
              hintText: 'Automatic routing — Let ASKa-Piyu choose',
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
          const SizedBox(height: 6),
          Text(
            'Not sure which office handles your concern? Leave this on '
            'Automatic Routing and ASKa-Piyu will send your ticket to the '
            'appropriate office.',
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12.5,
              height: 1.4,
            ),
          ),
          const SizedBox(height: 18),
          _FieldLabel(
            number: 2,
            label: 'Subject',
            helper: 'A short summary of what you need help with.',
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _subjectCtrl,
            validator: _validateTicketSubject,
            textInputAction: TextInputAction.next,
            decoration: _inputDecoration(
              hintText: 'Example: How can I request my transcript of records?',
            ),
          ),
          const SizedBox(height: 18),
          _FieldLabel(
            number: 3,
            label: 'Description',
            helper:
                'Include dates, reference numbers, offices visited, '
                'or steps you already tried.',
          ),
          const SizedBox(height: 6),
          TextFormField(
            controller: _descCtrl,
            validator: _validateTicketDescription,
            minLines: widget.compact ? 4 : 5,
            maxLines: widget.compact ? 6 : 7,
            decoration: _inputDecoration(
              hintText: 'Tell us what happened and what help you need.',
            ),
          ),
          const SizedBox(height: 18),
          _FieldLabel(
            number: 4,
            label: 'Attachment (optional)',
            helper:
                'Screenshot or document ($_attachmentFormatsLabel — '
                'max 10 MB).',
          ),
          const SizedBox(height: 6),
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
          const SizedBox(height: 20),
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

    final guidance = _SubmitTicketGuidance(
      attachmentFormatsLabel: _attachmentFormatsLabel,
    );

    // The form card and the guidance column are deliberately two independent
    // pieces of composition, not one shared bordered container -- wrapping
    // both in a single StudentPanel made the right column's white background
    // stretch down to match the (much taller) form, leaving a huge empty
    // bordered region below "File requirements". The guidance column's own
    // two cards already carry their own borders/backgrounds, so it needs no
    // outer panel at all; it simply sizes to its content.
    final formCard = StudentPanel(
      padding:
          widget.compact
              ? const EdgeInsets.fromLTRB(16, 16, 16, 16)
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
/// single source of truth so the field helper and the guidance panel never
/// drift from what the picker actually allows.
const _attachmentFormatsLabel =
    'JPG, JPEG, PNG, WebP, GIF, BMP, HEIC, TIFF, or PDF';

/// Right-side (desktop) / below-form (narrow) guidance column for the
/// Submit Ticket view. The "Tips" list is static UI copy; the file
/// requirements line always reflects the real accepted formats/size/count.
class _SubmitTicketGuidance extends StatelessWidget {
  final String attachmentFormatsLabel;

  const _SubmitTicketGuidance({required this.attachmentFormatsLabel});

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
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(14),
            border: Border.all(color: DesignTokens.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'File requirements',
                style: TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'You can attach one file ($attachmentFormatsLabel) with a '
                'maximum size of 10 MB.',
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 12.5,
                  height: 1.4,
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

/// Field label with an optional small numbered marker (1-4) -- a
/// navigation/hierarchy element for the Submit Ticket flow's numbered
/// steps, not a decorative icon.
class _FieldLabel extends StatelessWidget {
  final String label;
  final String helper;
  final int? number;

  const _FieldLabel({required this.label, required this.helper, this.number});

  @override
  Widget build(BuildContext context) {
    final text = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontWeight: FontWeight.w900,
          ),
        ),
        if (helper.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(
            helper,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              height: 1.35,
            ),
          ),
        ],
      ],
    );
    if (number == null) return text;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: 22,
          height: 22,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: DesignTokens.maroon.withValues(alpha: 0.10),
            borderRadius: BorderRadius.circular(7),
          ),
          child: Text(
            '$number',
            style: const TextStyle(
              color: DesignTokens.maroon,
              fontWeight: FontWeight.w900,
              fontSize: 12,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(child: text),
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

/// Plain, bullet-separated ticket metadata (office • category • updated •
/// replies) -- typography and a simple separator carry the hierarchy
/// instead of a row of decorative metadata icons. Each piece truncates on
/// its own so long office/category text can't break the card layout.
class _TicketMetaLine extends StatelessWidget {
  final List<String> parts;

  const _TicketMetaLine({required this.parts});

  @override
  Widget build(BuildContext context) {
    final nonEmpty = parts.where((p) => p.trim().isNotEmpty).toList();
    return Wrap(
      spacing: 8,
      runSpacing: 6,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        for (var i = 0; i < nonEmpty.length; i++) ...[
          if (i > 0)
            const Text(
              '•',
              style: TextStyle(color: DesignTokens.muted, fontSize: 12),
            ),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 220),
            child: Text(
              nonEmpty[i],
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.muted,
                fontSize: 12,
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class _ChipStyle {
  final Color color;

  const _ChipStyle(this.color);
}

InputDecoration _inputDecoration({required String hintText}) {
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

class _TicketNotification {
  final String id;
  final String? ticketId;
  final String type;
  final String title;
  final String body;
  final bool isRead;

  const _TicketNotification({
    required this.id,
    required this.ticketId,
    required this.type,
    required this.title,
    required this.body,
    required this.isRead,
  });

  factory _TicketNotification.fromJson(Map<String, dynamic> json) {
    return _TicketNotification(
      id: (json['id'] ?? '').toString(),
      ticketId: json['ticket_id']?.toString(),
      type: (json['type'] ?? '').toString(),
      title: (json['title'] ?? 'Update').toString(),
      body: (json['body'] ?? '').toString(),
      isRead: json['is_read'] == true,
    );
  }
}

class _NotificationsBanner extends StatelessWidget {
  final List<_TicketNotification> notifications;
  final int unreadCount;
  final VoidCallback onDismiss;

  const _NotificationsBanner({
    required this.notifications,
    required this.unreadCount,
    required this.onDismiss,
  });

  @override
  Widget build(BuildContext context) {
    return StudentPanel(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.notifications_active_rounded,
                color: DesignTokens.maroon,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '$unreadCount new ticket update${unreadCount == 1 ? '' : 's'}',
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
              ),
              TextButton(
                onPressed: onDismiss,
                child: const Text('Mark all read'),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ...notifications.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    item.title,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: DesignTokens.ink,
                    ),
                  ),
                  Text(
                    item.body,
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 13,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
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
