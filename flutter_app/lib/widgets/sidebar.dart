import 'package:flutter/material.dart';
import '../app_config.dart';
import '../app_route_observer.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/admin_management_pages.dart';
import '../screens/admin_panel_page.dart';
import '../screens/chatbot_page.dart';
import '../screens/incoming_transfers_page.dart';
import '../screens/knowledge_articles_page.dart';
import '../screens/knowledge_base_page.dart';
import '../screens/login_page.dart';
import '../screens/settings_page.dart';
import '../screens/student_home.dart';
import '../screens/my_tickets_page.dart';
import '../services/api_client.dart';

enum StudentNavItem {
  home,
  knowledgeBase,
  chatbot,
  myTickets,
  submitTicket,
  officeDashboard,
  officeAssignedTickets,
  officeIncomingTransfers,
  officeFaculty,
  officeKnowledgeBase,
  officeKnowledgeArticles,
  officeGenerateArticles,
  adminDashboard,
  adminAllTickets,
  adminIncomingTransfers,
  adminKnowledgeBase,
  adminKnowledgeArticles,
  adminGenerateArticles,
  adminUsersRoles,
  adminOffices,
  adminReports,
  settings,
}

class AppSidebar extends StatelessWidget {
  final StudentNavItem current;

  const AppSidebar({super.key, this.current = StudentNavItem.home});

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final user = auth.currentUser;
    final role = user?.role.trim().toLowerCase();
    final isStudent = role == 'student' || role == 'faculty';
    final isOffice = role == 'office';
    final isAdmin = role == 'admin';

    if (isAdmin) {
      return _AdminDarkSidebar(
        current: current,
        userName: user?.fullName ?? 'ASKa Admin',
        onNavigate: (item, label) => _navigate(context, item, label),
        onLogout: () {
          signOutToHome(context); // ignore: unawaited_futures
        },
      );
    }

    if (isOffice) {
      return _OfficeDarkSidebar(
        current: current,
        userName: user?.fullName ?? 'Office Staff',
        officeName: user?.officeName ?? 'Campus Office',
        onNavigate: (item, label) => _navigate(context, item, label),
        onLogout: () {
          signOutToHome(context); // ignore: unawaited_futures
        },
      );
    }

    final items = <_SidebarData>[];
    // Guest + student/faculty: public support shell.
    items.addAll(const [
      _SidebarData('Home', Icons.home_rounded, StudentNavItem.home),
      _SidebarData('Knowledge Base', Icons.menu_book_rounded,
          StudentNavItem.knowledgeBase),
      _SidebarData(
          'Ask ASKa-Piyu', Icons.chat_bubble_rounded, StudentNavItem.chatbot),
    ]);
    if (isStudent) {
      items.addAll(const [
        _SidebarData(
            'My Tickets', Icons.fact_check_rounded, StudentNavItem.myTickets),
        _SidebarData('Submit Ticket', Icons.add_task_rounded,
            StudentNavItem.submitTicket),
        _SidebarData(
            'Settings', Icons.settings_rounded, StudentNavItem.settings),
      ]);
    }

    final brandSubtitle =
        role == 'faculty' ? 'Faculty support' : 'Student support';

    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(right: BorderSide(color: DesignTokens.border)),
      ),
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding:
                  const EdgeInsets.symmetric(horizontal: 12.0, vertical: 18.0),
              child: Row(
                children: [
                  Image.asset(
                    'assets/logo.png',
                    width: 36,
                    height: 36,
                    fit: BoxFit.contain,
                    filterQuality: FilterQuality.high,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'ASKa-Piyu',
                          style: TextStyle(
                            fontWeight: FontWeight.w900,
                            fontSize: 15,
                            color: Color(0xFF5C0A0F),
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          brandSubtitle,
                          style: const TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 11,
                            color: DesignTokens.muted,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.only(top: 18.0, bottom: 18.0),
                itemCount: items.length,
                itemBuilder: (ctx, idx) {
                  final it = items[idx];
                  return _SidebarItem(
                    label: it.label,
                    icon: it.icon,
                    selected: current == it.item,
                    onTap: () => _navigate(context, it.item, it.label),
                  );
                },
                separatorBuilder: (_, __) => const SizedBox(height: 6),
              ),
            ),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
              child: user == null
                  ? _GuestAccount(
                      onLogin: () => Navigator.of(context).push(
                        MaterialPageRoute(builder: (_) => const LoginPage()),
                      ),
                    )
                  : _UserAccount(
                      userName: user.fullName,
                      role: user.role,
                      officeName: user.officeName,
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 14),
              child: Column(
                children: [
                  if (user != null) ...[
                    _SidebarItem(
                      label: 'Logout',
                      icon: Icons.logout_rounded,
                      selected: false,
                      showIcon: true,
                      onTap: () {
                        signOutToHome(context); // ignore: unawaited_futures
                      },
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  void _navigate(BuildContext context, StudentNavItem item, String label) {
    if (item == current && item != StudentNavItem.submitTicket) {
      Navigator.of(context).maybePop();
      return;
    }

    if (item == StudentNavItem.home) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const StudentHomePage()),
        (route) => false,
      );
      return;
    }

    if (item == StudentNavItem.knowledgeBase) {
      Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => const KnowledgeBasePage()));
      return;
    }

    if (item == StudentNavItem.chatbot) {
      Navigator.of(context)
          .push(MaterialPageRoute(builder: (_) => const ChatbotPage()));
      return;
    }

    if (item == StudentNavItem.myTickets) {
      openProtectedPage(
        context,
        builder: (_) => const MyTicketsPage(),
        requireVerifiedEmail: true,
        message: emailVerifyRequiredMessage,
      );
      return;
    }

    if (item == StudentNavItem.submitTicket) {
      openProtectedPage(
        context,
        builder: (_) => const MyTicketsPage(initialTab: 1),
        requireVerifiedEmail: true,
        message: emailVerifyRequiredMessage,
      );
      return;
    }

    if (item == StudentNavItem.officeDashboard) {
      openOfficePage(
        context,
        builder: (_) => const OfficeDashboardPage(),
      );
      return;
    }

    if (item == StudentNavItem.officeAssignedTickets) {
      openOfficePage(
        context,
        builder: (_) => const OfficeAssignedTicketsPage(),
      );
      return;
    }

    if (item == StudentNavItem.officeIncomingTransfers) {
      openOfficePage(
        context,
        builder: (_) => const IncomingTransfersPage(),
      );
      return;
    }

    if (item == StudentNavItem.officeFaculty) {
      openOfficePage(
        context,
        builder: (_) => const OfficeFacultyAccountsPage(),
      );
      return;
    }

    if (item == StudentNavItem.officeKnowledgeBase ||
        item == StudentNavItem.officeGenerateArticles) {
      openOfficePage(
        context,
        builder: (_) => AdminPanelPage(
          initialTab: item == StudentNavItem.officeGenerateArticles ? 1 : 0,
        ),
      );
      return;
    }

    if (item == StudentNavItem.officeKnowledgeArticles) {
      openOfficePage(
        context,
        builder: (_) => const KnowledgeArticlesPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminDashboard) {
      openAdminPage(
        context,
        builder: (_) => const AdminDashboardPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminIncomingTransfers) {
      openAdminPage(
        context,
        builder: (_) => const IncomingTransfersPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminAllTickets) {
      openAdminPage(
        context,
        builder: (_) => const AdminAllTicketsPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminKnowledgeBase ||
        item == StudentNavItem.adminGenerateArticles) {
      openAdminPage(
        context,
        builder: (_) => AdminPanelPage(
          initialTab: item == StudentNavItem.adminGenerateArticles ? 1 : 0,
        ),
      );
      return;
    }

    if (item == StudentNavItem.adminKnowledgeArticles) {
      openAdminPage(
        context,
        builder: (_) => const KnowledgeArticlesPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminUsersRoles) {
      openAdminPage(
        context,
        builder: (_) => const AdminUsersRolesPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminOffices) {
      openAdminPage(
        context,
        builder: (_) => const AdminOfficesPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminReports) {
      openAdminPage(
        context,
        builder: (_) => const AdminReportsPage(),
      );
      return;
    }

    if (item == StudentNavItem.settings) {
      openProtectedPage(
        context,
        builder: (_) => const SettingsPage(),
      );
      return;
    }

    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text('$label coming soon')));
  }
}

class _GuestAccount extends StatelessWidget {
  final VoidCallback onLogin;

  const _GuestAccount({required this.onLogin});

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(
      onPressed: onLogin,
      style: OutlinedButton.styleFrom(
        foregroundColor: DesignTokens.maroon,
        side: const BorderSide(color: DesignTokens.maroon),
        padding: const EdgeInsets.symmetric(vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
      child: const Text('Login'),
    );
  }
}

class _UserAccount extends StatelessWidget {
  final String userName;
  final String role;
  final String? officeName;

  const _UserAccount({
    required this.userName,
    required this.role,
    this.officeName,
  });

  @override
  Widget build(BuildContext context) {
    final subtitle = (officeName != null && officeName!.trim().isNotEmpty)
        ? '${role.trim().toUpperCase()} · ${officeName!.trim()}'
        : role.trim().toUpperCase();
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: DesignTokens.maroon.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.maroon.withValues(alpha: 0.13)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  userName.isEmpty ? 'ASKa-Piyu user' : userName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w900,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.maroon,
                    fontWeight: FontWeight.w800,
                    fontSize: 10,
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

class _SidebarItem extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback? onTap;
  final bool showIcon;

  const _SidebarItem({
    required this.label,
    required this.icon,
    required this.selected,
    this.onTap,
    this.showIcon = false,
  });

  @override
  Widget build(BuildContext context) {
    final foreground = selected ? DesignTokens.maroon : DesignTokens.muted;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Material(
        color: selected
            ? DesignTokens.maroon.withValues(alpha: 0.09)
            : Colors.transparent,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          borderRadius: BorderRadius.circular(14),
          onTap: onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(14),
              border: Border.all(
                color: selected
                    ? DesignTokens.maroon.withValues(alpha: 0.16)
                    : Colors.transparent,
              ),
            ),
            child: Row(
              children: [
                if (showIcon) ...[
                  Icon(icon, size: 18, color: foreground),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: selected ? FontWeight.w900 : FontWeight.w700,
                      color: foreground,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SidebarData {
  final String label;
  final IconData icon;
  final StudentNavItem item;

  const _SidebarData(this.label, this.icon, this.item);
}

class _AdminNavGroup {
  final String title;
  final List<_SidebarData> items;

  const _AdminNavGroup(this.title, this.items);
}

class _AdminDarkSidebar extends StatelessWidget {
  final StudentNavItem current;
  final String userName;
  final void Function(StudentNavItem item, String label) onNavigate;
  final VoidCallback onLogout;

  const _AdminDarkSidebar({
    required this.current,
    required this.userName,
    required this.onNavigate,
    required this.onLogout,
  });

  static const groups = <_AdminNavGroup>[
    _AdminNavGroup('Support Management', [
      _SidebarData(
          'Dashboard', Icons.dashboard_rounded, StudentNavItem.adminDashboard),
      _SidebarData(
          'All Tickets', Icons.fact_check_rounded, StudentNavItem.adminAllTickets),
      _SidebarData('Incoming Transfers', Icons.swap_horiz_rounded,
          StudentNavItem.adminIncomingTransfers),
      _SidebarData('Knowledge Base', Icons.library_books_rounded,
          StudentNavItem.adminKnowledgeBase),
      _SidebarData('Knowledge Article', Icons.article_outlined,
          StudentNavItem.adminKnowledgeArticles),
    ]),
    _AdminNavGroup('User & Organization', [
      _SidebarData('Users & Roles', Icons.manage_accounts_rounded,
          StudentNavItem.adminUsersRoles),
      _SidebarData(
          'Offices', Icons.apartment_rounded, StudentNavItem.adminOffices),
    ]),
    _AdminNavGroup('Reports & Analytics', [
      _SidebarData(
          'Reports', Icons.insights_rounded, StudentNavItem.adminReports),
    ]),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      color: DesignTokens.adminSidebarBg,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 18),
              child: Row(
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      color: const Color(0xFF7A1218),
                      borderRadius:
                          BorderRadius.circular(DesignTokens.adminRadius),
                      border: Border.all(color: const Color(0xFF9A2A32)),
                    ),
                    padding: const EdgeInsets.all(6),
                    child: Image.asset(
                      'assets/logo.png',
                      fit: BoxFit.contain,
                      filterQuality: FilterQuality.high,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Text(
                      'ASKa-Piyu Admin Panel',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                        fontSize: 14,
                        height: 1.25,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(10, 4, 10, 16),
                children: [
                  for (final group in groups) ...[
                    Padding(
                      padding: const EdgeInsets.fromLTRB(10, 14, 10, 8),
                      child: Text(
                        group.title.toUpperCase(),
                        style: const TextStyle(
                          color: DesignTokens.adminSidebarMuted,
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          letterSpacing: 0.6,
                        ),
                      ),
                    ),
                    for (final item in group.items)
                      _AdminSidebarItem(
                        label: item.label,
                        icon: item.icon,
                        selected: current == item.item,
                        onTap: () => onNavigate(item.item, item.label),
                        trailing: item.item == StudentNavItem.adminIncomingTransfers
                            ? const TransferBadge()
                            : null,
                      ),
                  ],
                ],
              ),
            ),
            const Divider(height: 1, color: Color(0xFF6B1A20)),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 18,
                    backgroundColor: const Color(0xFF7A1218),
                    child: Text(
                      userName.isEmpty
                          ? 'A'
                          : userName.trim()[0].toUpperCase(),
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          userName.isEmpty ? 'ASKa Admin' : userName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'Administrator',
                          style: TextStyle(
                            color: DesignTokens.adminSidebarMuted,
                            fontWeight: FontWeight.w600,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 14),
              child: _AdminSidebarItem(
                label: 'Logout',
                icon: Icons.logout_rounded,
                selected: false,
                showIcon: true,
                onTap: onLogout,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AdminSidebarItem extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback? onTap;
  final bool showIcon;
  final Widget? trailing;

  const _AdminSidebarItem({
    required this.label,
    required this.icon,
    required this.selected,
    this.onTap,
    this.showIcon = false,
    this.trailing,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Material(
        color: selected ? DesignTokens.adminSidebarActive : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                if (showIcon) ...[
                  Icon(
                    icon,
                    size: 18,
                    color: selected
                        ? Colors.white
                        : DesignTokens.adminSidebarText,
                  ),
                  const SizedBox(width: 10),
                ],
                Expanded(
                  child: Text(
                    label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight:
                          selected ? FontWeight.w800 : FontWeight.w600,
                      color: selected
                          ? Colors.white
                          : DesignTokens.adminSidebarText,
                    ),
                  ),
                ),
                if (trailing != null) trailing!,
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Bumped by actions elsewhere in the app (a successful Accept/Reject, the
/// explicit "mark transfer notifications read" action on the mailbox
/// screen) that change the authenticated user's unread-transfer count.
/// TransferBadge listens to this in addition to its own
/// didChangeDependencies, since it's a sibling widget to those actions
/// with no other connection to them -- returning to the mailbox via a
/// fresh page push already gets a fresh fetch for free (a new widget
/// instance), but an action taken while the SAME sidebar instance stays
/// mounted would otherwise never be reflected. Each TransferBadge instance
/// ignores this tick while its own page is covered by another route (see
/// RouteAware below), so a bump never causes a fetch for a hidden page's
/// badge -- only the one(s) the user can actually see.
final ValueNotifier<int> transferBadgeRefreshTick = ValueNotifier<int>(0);

/// Test-only: incremented every time any TransferBadge actually attempts
/// a fetch (regardless of whether the network call itself succeeds).
/// There is no HTTP-mocking seam in this codebase's widget tests, so this
/// is the only way to deterministically observe "did a fetch happen" vs.
/// "was it correctly skipped because the page is hidden" without a real
/// backend. Never read by production code.
@visibleForTesting
int debugTransferBadgeLoadAttempts = 0;

/// Unread-count badge for the transfer workflow. Counts only unread
/// notifications whose type is exclusive to the transfer workflow, via a
/// dedicated, un-paginated count endpoint -- never the global unread_count,
/// and never a substitute like the pending-request count. Public (not
/// private to this file) since it's also used as the Office Dashboard's
/// mailbox-button badge (see _OfficeDashboardMailboxButton in
/// admin_management_pages.dart) in addition to the "Incoming Transfers"
/// nav item here -- both read the same count and the same refresh
/// mechanism, so this is reused rather than duplicated. Multiple
/// simultaneous instances are expected and already accounted for (see
/// debugTransferBadgeLoadAttempts below).
class TransferBadge extends StatefulWidget {
  const TransferBadge({super.key});

  @override
  State<TransferBadge> createState() => _TransferBadgeState();
}

class _TransferBadgeState extends State<TransferBadge> with RouteAware {
  int? _count;
  ModalRoute<dynamic>? _route;
  // A badge is visible as soon as it's built, by construction (a page is
  // always the top of the stack at the moment it's first pushed); this
  // only ever turns false once didPushNext() reports another route
  // covering it.
  bool _visible = true;

  @override
  void initState() {
    super.initState();
    transferBadgeRefreshTick.addListener(_onRefreshTick);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final route = ModalRoute.of(context);
    if (route != _route) {
      appRouteObserver.unsubscribe(this);
      _route = route;
      if (route is PageRoute) {
        appRouteObserver.subscribe(this, route);
      }
    }
    _load();
  }

  @override
  void dispose() {
    transferBadgeRefreshTick.removeListener(_onRefreshTick);
    appRouteObserver.unsubscribe(this);
    super.dispose();
  }

  @override
  void didPushNext() {
    // Another route was pushed on top of this badge's own page -- it's
    // hidden now, so stop treating refresh-tick bumps as a reason to
    // fetch until it's visible again.
    _visible = false;
  }

  @override
  void didPopNext() {
    // The route that was covering this page is gone and it's visible
    // again. Refresh unconditionally rather than relying on having seen
    // a refresh-tick bump while hidden -- there may not have been one,
    // and the count could still be stale from whatever changed while
    // this page was covered.
    _visible = true;
    _load();
  }

  void _onRefreshTick() {
    if (!_visible) return;
    _load();
  }

  Future<void> _load() async {
    debugTransferBadgeLoadAttempts++;
    final auth = AuthScope.of(context);
    if (auth.role != 'office' && auth.role != 'admin') return;
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/notifications/transfers/unread-count',
        headers: auth.ticketHeaders(),
      );
      if (!result.ok) return;
      final count = result.jsonObject['unread_count'];
      if (mounted && count is int) setState(() => _count = count);
    } catch (_) {
      // Non-blocking: navigation still works without the badge.
    }
  }

  @override
  Widget build(BuildContext context) {
    final count = _count;
    if (count == null || count <= 0) return const SizedBox.shrink();
    return Container(
      margin: const EdgeInsets.only(left: 8),
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: DesignTokens.maroon,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        count > 9 ? '9+' : '$count',
        style: const TextStyle(
          color: Colors.white,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

String _officeAvatarLabel(String officeName, String userName) {
  final match = RegExp(r'\(([^)]+)\)\s*$').firstMatch(officeName.trim());
  if (match != null) {
    final abbr = match.group(1)!.trim();
    if (abbr.isNotEmpty) {
      return abbr.length <= 4
          ? abbr.toUpperCase()
          : abbr.substring(0, 4).toUpperCase();
    }
  }
  final source =
      userName.trim().isNotEmpty ? userName.trim() : officeName.trim();
  if (source.isEmpty) return 'O';
  final parts =
      source.split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return source.substring(0, source.length >= 2 ? 2 : 1).toUpperCase();
}

class _OfficeDarkSidebar extends StatelessWidget {
  final StudentNavItem current;
  final String userName;
  final String officeName;
  final void Function(StudentNavItem item, String label) onNavigate;
  final VoidCallback onLogout;

  const _OfficeDarkSidebar({
    required this.current,
    required this.userName,
    required this.officeName,
    required this.onNavigate,
    required this.onLogout,
  });

  static const items = <_SidebarData>[
    _SidebarData('Dashboard', Icons.dashboard_customize_rounded,
        StudentNavItem.officeDashboard),
    _SidebarData('Assigned Tickets', Icons.assignment_turned_in_rounded,
        StudentNavItem.officeAssignedTickets),
    // Incoming Transfers is deliberately not a sidebar item here -- the
    // Office Dashboard's own Mailbox button (beside the date/time card)
    // is now the single entry point, reusing the same page and the same
    // TransferBadge unread count. Removing this avoided a redundant
    // second nav item pointing at the identical page.
    _SidebarData(
        'Account', Icons.manage_accounts_outlined, StudentNavItem.officeFaculty),
    _SidebarData('Knowledge Base', Icons.library_books_rounded,
        StudentNavItem.officeKnowledgeBase),
    _SidebarData('Knowledge Article', Icons.article_outlined,
        StudentNavItem.officeKnowledgeArticles),
  ];

  @override
  Widget build(BuildContext context) {
    final avatar = _officeAvatarLabel(officeName, userName);
    return Container(
      color: DesignTokens.adminSidebarBg,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 18),
              child: Row(
                children: [
                  Container(
                    width: 38,
                    height: 38,
                    decoration: BoxDecoration(
                      color: const Color(0xFF7A1218),
                      borderRadius:
                          BorderRadius.circular(DesignTokens.adminRadius),
                      border: Border.all(color: const Color(0xFF9A2A32)),
                    ),
                    padding: const EdgeInsets.all(6),
                    child: Image.asset(
                      'assets/logo.png',
                      fit: BoxFit.contain,
                      filterQuality: FilterQuality.high,
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'ASKa-Piyu',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w900,
                            fontSize: 15,
                          ),
                        ),
                        SizedBox(height: 2),
                        Text(
                          'Office workspace',
                          style: TextStyle(
                            color: DesignTokens.adminSidebarMuted,
                            fontWeight: FontWeight.w700,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(10, 4, 10, 16),
                children: [
                  const Padding(
                    padding: EdgeInsets.fromLTRB(10, 8, 10, 8),
                    child: Text(
                      'WORKSPACE',
                      style: TextStyle(
                        color: DesignTokens.adminSidebarMuted,
                        fontSize: 10,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 0.6,
                      ),
                    ),
                  ),
                  for (final item in items)
                    _AdminSidebarItem(
                      label: item.label,
                      icon: item.icon,
                      selected: current == item.item,
                      onTap: () => onNavigate(item.item, item.label),
                    ),
                ],
              ),
            ),
            const Divider(height: 1, color: Color(0xFF6B1A20)),
            Padding(
              padding: const EdgeInsets.fromLTRB(14, 14, 14, 8),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 18,
                    backgroundColor: const Color(0xFF7A1218),
                    child: Text(
                      avatar,
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w800,
                        fontSize: avatar.length > 2 ? 9 : 12,
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          officeName,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                            fontSize: 12,
                            height: 1.25,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          userName.isEmpty ? 'Office staff' : userName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: DesignTokens.adminSidebarMuted,
                            fontWeight: FontWeight.w600,
                            fontSize: 11,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(10, 0, 10, 14),
              child: _AdminSidebarItem(
                label: 'Logout',
                icon: Icons.logout_rounded,
                selected: false,
                showIcon: true,
                onTap: onLogout,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
