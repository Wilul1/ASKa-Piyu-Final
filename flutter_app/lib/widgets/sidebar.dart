import 'package:flutter/material.dart';
import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../screens/admin_management_pages.dart';
import '../screens/admin_panel_page.dart';
import '../screens/admin_generate_articles_page.dart';
import '../screens/chatbot_page.dart';
import '../screens/knowledge_base_page.dart';
import '../screens/login_page.dart';
import '../screens/student_home.dart';
import '../screens/my_tickets_page.dart';

enum StudentNavItem {
  home,
  knowledgeBase,
  chatbot,
  myTickets,
  submitTicket,
  officeDashboard,
  officeAssignedTickets,
  adminDashboard,
  adminAllTickets,
  adminKnowledgeBase,
  adminGenerateArticles,
  adminUsersRoles,
  adminOffices,
  adminReports,
  announcements,
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
    final isStudent = role == 'student';
    final isOffice = role == 'office';
    final isAdmin = role == 'admin';

    final items = <_SidebarData>[];
    if (isOffice) {
      items.addAll(const [
        _SidebarData('Dashboard', Icons.dashboard_customize_rounded,
            StudentNavItem.officeDashboard),
        _SidebarData('Assigned Tickets', Icons.assignment_turned_in_rounded,
            StudentNavItem.officeAssignedTickets),
      ]);
    } else if (isAdmin) {
      items.addAll(const [
        _SidebarData('Dashboard', Icons.dashboard_rounded,
            StudentNavItem.adminDashboard),
        _SidebarData(
            'All Tickets', Icons.fact_check_rounded, StudentNavItem.adminAllTickets),
        _SidebarData('Knowledge Base', Icons.library_books_rounded,
            StudentNavItem.adminKnowledgeBase),
        _SidebarData('Generate Articles', Icons.auto_awesome_rounded,
            StudentNavItem.adminGenerateArticles),
        _SidebarData('Users & Roles', Icons.manage_accounts_rounded,
            StudentNavItem.adminUsersRoles),
        _SidebarData(
            'Offices', Icons.apartment_rounded, StudentNavItem.adminOffices),
      ]);
    } else {
      // Guest + student: public/student support shell.
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
        ]);
      }
    }

    final brandSubtitle = isOffice
        ? 'Office workspace'
        : isAdmin
            ? 'Admin workspace'
            : 'Student support';

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
                      onTap: () {
                        auth.logout();
                        Navigator.of(context).pushAndRemoveUntil(
                          MaterialPageRoute(
                              builder: (_) => const StudentHomePage()),
                          (route) => false,
                        );
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
      );
      return;
    }

    if (item == StudentNavItem.submitTicket) {
      openProtectedPage(
        context,
        builder: (_) => const MyTicketsPage(initialTab: 1),
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

    if (item == StudentNavItem.adminDashboard) {
      openAdminPage(
        context,
        builder: (_) => const AdminDashboardPage(),
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

    if (item == StudentNavItem.adminKnowledgeBase) {
      openAdminPage(
        context,
        builder: (_) => const AdminPanelPage(),
      );
      return;
    }

    if (item == StudentNavItem.adminGenerateArticles) {
      openAdminPage(
        context,
        builder: (_) => const AdminGenerateArticlesPage(),
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
          const Icon(Icons.account_circle_rounded,
              color: DesignTokens.maroon, size: 28),
          const SizedBox(width: 9),
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

  const _SidebarItem({
    required this.label,
    required this.icon,
    required this.selected,
    this.onTap,
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
                Container(
                  width: 34,
                  height: 34,
                  decoration: BoxDecoration(
                    color: selected
                        ? DesignTokens.maroon
                        : DesignTokens.maroon.withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(11),
                  ),
                  child: Icon(icon,
                      color: selected ? Colors.white : DesignTokens.maroon,
                      size: 19),
                ),
                const SizedBox(width: 10),
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
