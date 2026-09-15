part of 'admin_management_pages.dart';

enum _OfficeAccountGroup { staff, faculty }

class OfficeFacultyAccountsPage extends StatefulWidget {
  /// Seeded users skip network load. Widget tests only.
  @visibleForTesting
  final List<Map<String, dynamic>>? debugUsers;

  /// Force the loading chrome without a network call. Widget tests only.
  @visibleForTesting
  final bool debugLoading;

  /// Force the error chrome without a network call. Widget tests only.
  @visibleForTesting
  final String? debugError;

  /// Intercepts account creation in widget tests. Production remains
  /// `POST /auth/office-accounts` and `POST /auth/faculty-accounts`.
  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required bool staff,
    required String fullName,
    required String email,
    required String password,
  })?
  debugCreateAccount;

  const OfficeFacultyAccountsPage({
    super.key,
    this.debugUsers,
    this.debugLoading = false,
    this.debugError,
    this.debugCreateAccount,
  });

  @override
  State<OfficeFacultyAccountsPage> createState() =>
      _OfficeFacultyAccountsPageState();
}

class _OfficeFacultyAccountsPageState extends State<OfficeFacultyAccountsPage> {
  final List<_AdminUserEntry> _staff = [];
  final List<_AdminUserEntry> _faculty = [];
  final _staffSearchCtrl = TextEditingController();
  final _facultySearchCtrl = TextEditingController();
  final _staffPanelKey = GlobalKey();
  final _facultyPanelKey = GlobalKey();
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;
  _OfficeAccountGroup _focusedGroup = _OfficeAccountGroup.staff;

  @override
  void initState() {
    super.initState();
    _staffSearchCtrl.addListener(() => setState(() {}));
    _facultySearchCtrl.addListener(() => setState(() {}));
    final seeded = widget.debugUsers;
    if (seeded != null) {
      _requestedInitialLoad = true;
      _loading = widget.debugLoading;
      _error = widget.debugError;
      _replaceUsers(seeded);
    } else if (widget.debugLoading || widget.debugError != null) {
      _requestedInitialLoad = true;
      _loading = widget.debugLoading;
      _error = widget.debugError;
    }
  }

  @override
  void dispose() {
    _staffSearchCtrl.dispose();
    _facultySearchCtrl.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final auth = AuthScope.of(context);
    if (auth.role == 'office' && !_requestedInitialLoad) {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _load();
      });
    }
  }

  void _replaceUsers(List<Map<String, dynamic>> raw) {
    final users = raw.map((item) => _AdminUserEntry.fromJson(item)).toList();
    _staff
      ..clear()
      ..addAll(users.where((user) => user.role == 'office'));
    _faculty
      ..clear()
      ..addAll(users.where((user) => user.role == 'faculty'));
  }

  Future<void> _load() async {
    if (widget.debugUsers != null ||
        widget.debugLoading ||
        widget.debugError != null) {
      setState(() {
        _loading = widget.debugLoading;
        _error = widget.debugError;
        if (widget.debugUsers != null) {
          _replaceUsers(widget.debugUsers!);
        }
      });
      return;
    }

    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final users = await _loadAdminUsers(context);
      if (!mounted) return;
      setState(() {
        _staff
          ..clear()
          ..addAll(users.where((user) => user.role == 'office'));
        _faculty
          ..clear()
          ..addAll(users.where((user) => user.role == 'faculty'));
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  List<_AdminUserEntry> get _visibleStaff =>
      _staff
          .where((user) => user.matchesNameOrEmail(_staffSearchCtrl.text))
          .toList();

  List<_AdminUserEntry> get _visibleFaculty =>
      _faculty
          .where((user) => user.matchesNameOrEmail(_facultySearchCtrl.text))
          .toList();

  Future<void> _openCreateDrawer({required bool staff}) async {
    final previousFocus = FocusManager.instance.primaryFocus;
    final created = await showGeneralDialog<_AdminUserEntry>(
      context: context,
      barrierDismissible: false,
      barrierLabel: staff ? 'Add Office Staff Account' : 'Add Faculty Account',
      barrierColor: Colors.black.withValues(alpha: 0.32),
      transitionDuration: const Duration(milliseconds: 280),
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        return Align(
          key: const Key('office-account-create-align'),
          alignment: Alignment.centerRight,
          child: _OfficeAccountCreationDrawer(
            createStaff: staff,
            onCreate: ({required fullName, required email, required password}) {
              return _submitOfficeAccountCreate(
                dialogContext,
                staff: staff,
                fullName: fullName,
                email: email,
                password: password,
              );
            },
          ),
        );
      },
      transitionBuilder: (context, animation, secondaryAnimation, child) {
        final curved = CurvedAnimation(
          parent: animation,
          curve: Curves.easeOutCubic,
          reverseCurve: Curves.easeInCubic,
        );
        return SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(1, 0),
            end: Offset.zero,
          ).animate(curved),
          child: child,
        );
      },
    );
    if (previousFocus != null && previousFocus.canRequestFocus) {
      previousFocus.requestFocus();
    }
    if (created == null || !mounted) return;
    await _load();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          staff
              ? 'Office staff login created for ${created.email}. '
                  'They will open this office workspace on sign-in.'
              : 'Faculty login created for ${created.email}. '
                  'Share the temporary password securely.',
        ),
      ),
    );
  }

  Future<_AdminUserEntry> _submitOfficeAccountCreate(
    BuildContext dialogContext, {
    required bool staff,
    required String fullName,
    required String email,
    required String password,
  }) async {
    final debugCreate = widget.debugCreateAccount;
    if (debugCreate != null) {
      final raw = await debugCreate(
        staff: staff,
        fullName: fullName,
        email: email,
        password: password,
      );
      return _AdminUserEntry.fromJson(raw);
    }
    if (staff) {
      return _createOfficeStaffAccountRequest(
        dialogContext,
        fullName: fullName,
        email: email,
        password: password,
      );
    }
    return _createFacultyAccountRequest(
      dialogContext,
      fullName: fullName,
      email: email,
      password: password,
    );
  }

  void _focusGroup(_OfficeAccountGroup group, {required bool scrollToPanel}) {
    setState(() => _focusedGroup = group);
    if (!scrollToPanel) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final target =
          group == _OfficeAccountGroup.staff
              ? _staffPanelKey.currentContext
              : _facultyPanelKey.currentContext;
      if (target == null) return;
      Scrollable.ensureVisible(
        target,
        duration: const Duration(milliseconds: 280),
        curve: Curves.easeOutCubic,
        alignment: 0.08,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = AuthScope.of(context);
    final officeName = auth.currentUser?.officeName ?? 'your office';

    return OfficeScaffold(
      current: StudentNavItem.officeFaculty,
      title: 'Account',
      description:
          'Monitor and manage office staff and faculty logins for $officeName.',
      fillBody: true,
      showHeader: false,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_loading) const LinearProgressIndicator(minHeight: 3),
          Expanded(
            child: LayoutBuilder(
              builder: (context, constraints) {
                final wide = constraints.maxWidth >= 900;
                final compact = constraints.maxWidth < 720;
                return SingleChildScrollView(
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    24,
                  ),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 1180),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        _OfficeAccountHeader(
                          officeName: officeName,
                          onCreateStaff: () => _openCreateDrawer(staff: true),
                          onCreateFaculty:
                              () => _openCreateDrawer(staff: false),
                        ),
                        const SizedBox(height: 16),
                        _OfficeAccountTypeControl(
                          focused: _focusedGroup,
                          onChanged:
                              (group) =>
                                  _focusGroup(group, scrollToPanel: wide),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: 14),
                          _AdminNotice(
                            icon: Icons.info_outline_rounded,
                            message: _error!,
                          ),
                        ],
                        const SizedBox(height: 16),
                        if (wide || _focusedGroup == _OfficeAccountGroup.staff)
                          _OfficeAccountPanel(
                            key: _staffPanelKey,
                            title: 'Office Staff Accounts',
                            subtitle:
                                'Staff accounts can sign in to the office workspace (tickets, KB, add to KB).',
                            searchCtrl: _staffSearchCtrl,
                            searchKey: const Key('office-staff-search'),
                            users: _visibleStaff,
                            totalCount: _staff.length,
                            loading: _loading,
                            compact: compact,
                            emptyTitle: 'No office staff accounts yet',
                            emptyBody:
                                'Create a staff login so another office worker can manage assigned tickets without sharing this account.',
                            noResultsTitle: 'No matching staff accounts',
                            noResultsBody:
                                'Try a different name or email, or clear the search.',
                            roleLabel: 'Office Staff',
                          ),
                        if (wide) const SizedBox(height: 16),
                        if (wide ||
                            _focusedGroup == _OfficeAccountGroup.faculty)
                          _OfficeAccountPanel(
                            key: _facultyPanelKey,
                            title: 'Faculty Accounts',
                            subtitle:
                                'Faculty accounts can sign in and use faculty Knowledge Base tools. They do not open the office ticket console.',
                            searchCtrl: _facultySearchCtrl,
                            searchKey: const Key('office-faculty-search'),
                            users: _visibleFaculty,
                            totalCount: _faculty.length,
                            loading: _loading,
                            compact: compact,
                            emptyTitle: 'No faculty accounts yet',
                            emptyBody:
                                'Create a login so faculty can access campus support tools for your office.',
                            noResultsTitle: 'No matching faculty accounts',
                            noResultsBody:
                                'Try a different name or email, or clear the search.',
                            roleLabel: 'Faculty',
                          ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _OfficeAccountHeader extends StatelessWidget {
  final String officeName;
  final VoidCallback onCreateStaff;
  final VoidCallback onCreateFaculty;

  const _OfficeAccountHeader({
    required this.officeName,
    required this.onCreateStaff,
    required this.onCreateFaculty,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'USER ACCOUNTS',
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 11,
                  fontWeight: FontWeight.w800,
                  letterSpacing: 1.1,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Account',
                style: TextStyle(
                  color: DesignTokens.ink,
                  fontSize: 28,
                  fontWeight: FontWeight.w900,
                  height: 1.1,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'Monitor and manage office staff and faculty logins for $officeName.',
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  height: 1.35,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(width: 12),
        PopupMenuButton<String>(
          key: const Key('office-add-account'),
          tooltip: 'Add Account',
          offset: const Offset(0, 8),
          color: Colors.white,
          onSelected: (value) {
            if (value == 'staff') onCreateStaff();
            if (value == 'faculty') onCreateFaculty();
          },
          itemBuilder:
              (context) => const [
                PopupMenuItem<String>(
                  key: Key('add-office-staff'),
                  value: 'staff',
                  child: Text('Office Staff'),
                ),
                PopupMenuItem<String>(
                  key: Key('add-office-faculty'),
                  value: 'faculty',
                  child: Text('Faculty'),
                ),
              ],
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 11),
            decoration: BoxDecoration(
              color: DesignTokens.maroon,
              borderRadius: BorderRadius.circular(10),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(
                  'Add Account',
                  style: TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                  ),
                ),
                SizedBox(width: 4),
                Icon(
                  Icons.arrow_drop_down_rounded,
                  color: Colors.white,
                  size: 22,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _OfficeAccountTypeControl extends StatelessWidget {
  final _OfficeAccountGroup focused;
  final ValueChanged<_OfficeAccountGroup> onChanged;

  const _OfficeAccountTypeControl({
    required this.focused,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          color: const Color(0xFFF1F5F9),
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _segment(
              label: 'Office Staff',
              selected: focused == _OfficeAccountGroup.staff,
              onTap: () => onChanged(_OfficeAccountGroup.staff),
            ),
            _segment(
              label: 'Faculty',
              selected: focused == _OfficeAccountGroup.faculty,
              onTap: () => onChanged(_OfficeAccountGroup.faculty),
            ),
          ],
        ),
      ),
    );
  }

  Widget _segment({
    required String label,
    required bool selected,
    required VoidCallback onTap,
  }) {
    return Material(
      color: selected ? DesignTokens.maroon : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? Colors.white : DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ),
      ),
    );
  }
}

class _OfficeAccountPanel extends StatelessWidget {
  final String title;
  final String subtitle;
  final TextEditingController searchCtrl;
  final Key searchKey;
  final List<_AdminUserEntry> users;
  final int totalCount;
  final bool loading;
  final bool compact;
  final String emptyTitle;
  final String emptyBody;
  final String noResultsTitle;
  final String noResultsBody;
  final String roleLabel;

  const _OfficeAccountPanel({
    super.key,
    required this.title,
    required this.subtitle,
    required this.searchCtrl,
    required this.searchKey,
    required this.users,
    required this.totalCount,
    required this.loading,
    required this.compact,
    required this.emptyTitle,
    required this.emptyBody,
    required this.noResultsTitle,
    required this.noResultsBody,
    required this.roleLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          LayoutBuilder(
            builder: (context, constraints) {
              final stacked = constraints.maxWidth < 640;
              final searchField = SizedBox(
                width: stacked ? double.infinity : 260,
                child: _OfficeAccountSearchField(
                  key: searchKey,
                  controller: searchCtrl,
                ),
              );
              final heading = Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      color: DesignTokens.ink,
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      height: 1.35,
                    ),
                  ),
                ],
              );
              if (stacked) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [heading, const SizedBox(height: 12), searchField],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: heading),
                  const SizedBox(width: 16),
                  searchField,
                ],
              );
            },
          ),
          const SizedBox(height: 16),
          if (loading && totalCount == 0)
            const _OfficeAccountState(
              title: 'Loading accounts',
              body: 'Fetching staff and faculty logins for your office.',
            )
          else if (totalCount == 0)
            _OfficeAccountState(title: emptyTitle, body: emptyBody)
          else if (users.isEmpty)
            _OfficeAccountState(title: noResultsTitle, body: noResultsBody)
          else if (compact)
            _OfficeAccountCardList(users: users, roleLabel: roleLabel)
          else
            _OfficeAccountTable(users: users, roleLabel: roleLabel),
        ],
      ),
    );
  }
}

class _OfficeAccountSearchField extends StatelessWidget {
  final TextEditingController controller;

  const _OfficeAccountSearchField({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      decoration: InputDecoration(
        hintText: 'Search name or email...',
        prefixIcon: const Icon(Icons.search_rounded, size: 18),
        isDense: true,
        filled: true,
        fillColor: const Color(0xFFF8FAFC),
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 10,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: DesignTokens.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.2),
        ),
      ),
    );
  }
}

class _OfficeAccountState extends StatelessWidget {
  final String title;
  final String body;

  const _OfficeAccountState({required this.title, required this.body});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36),
      child: Column(
        children: [
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            body,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }
}

class _OfficeAccountTable extends StatelessWidget {
  final List<_AdminUserEntry> users;
  final String roleLabel;

  const _OfficeAccountTable({required this.users, required this.roleLabel});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(8, 0, 8, 8),
          child: Row(
            children: [
              SizedBox(width: 36, child: Text('#', style: _kTableHeader)),
              Expanded(flex: 3, child: Text('NAME', style: _kTableHeader)),
              Expanded(flex: 3, child: Text('EMAIL', style: _kTableHeader)),
              Expanded(flex: 2, child: Text('ROLE', style: _kTableHeader)),
              Expanded(
                flex: 2,
                child: Text('DATE ADDED', style: _kTableHeader),
              ),
              Expanded(flex: 2, child: Text('STATUS', style: _kTableHeader)),
            ],
          ),
        ),
        const Divider(height: 1, color: DesignTokens.border),
        for (var i = 0; i < users.length; i++) ...[
          _OfficeAccountTableRow(
            index: i + 1,
            user: users[i],
            roleLabel: roleLabel,
          ),
          if (i != users.length - 1)
            const Divider(height: 1, color: DesignTokens.border),
        ],
      ],
    );
  }
}

class _OfficeAccountTableRow extends StatelessWidget {
  final int index;
  final _AdminUserEntry user;
  final String roleLabel;

  const _OfficeAccountTableRow({
    required this.index,
    required this.user,
    required this.roleLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
      child: Row(
        children: [
          SizedBox(
            width: 36,
            child: Text(
              '$index',
              style: const TextStyle(
                color: DesignTokens.muted,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              user.fullName,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              user.email,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.muted,
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              roleLabel,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              user.createdAt == null
                  ? '—'
                  : _adminFormatAssignedDate(user.createdAt!),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w600,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Align(
              alignment: Alignment.centerLeft,
              child: _OfficeAccountStatusBadge(active: user.isActive),
            ),
          ),
        ],
      ),
    );
  }
}

class _OfficeAccountCardList extends StatelessWidget {
  final List<_AdminUserEntry> users;
  final String roleLabel;

  const _OfficeAccountCardList({required this.users, required this.roleLabel});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < users.length; i++) ...[
          _OfficeAccountCard(
            index: i + 1,
            user: users[i],
            roleLabel: roleLabel,
          ),
          if (i != users.length - 1) const SizedBox(height: 10),
        ],
      ],
    );
  }
}

class _OfficeAccountCard extends StatelessWidget {
  final int index;
  final _AdminUserEntry user;
  final String roleLabel;

  const _OfficeAccountCard({
    required this.index,
    required this.user,
    required this.roleLabel,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                '$index',
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontWeight: FontWeight.w700,
                  fontSize: 12,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  user.fullName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w800,
                    fontSize: 14,
                  ),
                ),
              ),
              _OfficeAccountStatusBadge(active: user.isActive),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            user.email,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 13,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            [
              roleLabel,
              if (user.createdAt != null)
                _adminFormatAssignedDate(user.createdAt!),
            ].join(' · '),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _OfficeAccountStatusBadge extends StatelessWidget {
  final bool active;

  const _OfficeAccountStatusBadge({required this.active});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: active ? const Color(0xFFDCFCE7) : const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        active ? 'Active' : 'Inactive',
        style: TextStyle(
          color: active ? const Color(0xFF15803D) : DesignTokens.muted,
          fontWeight: FontWeight.w800,
          fontSize: 11,
        ),
      ),
    );
  }
}

class _OfficeAccountCreationDrawer extends StatefulWidget {
  final bool createStaff;
  final Future<_AdminUserEntry> Function({
    required String fullName,
    required String email,
    required String password,
  })
  onCreate;

  const _OfficeAccountCreationDrawer({
    required this.createStaff,
    required this.onCreate,
  });

  @override
  State<_OfficeAccountCreationDrawer> createState() =>
      _OfficeAccountCreationDrawerState();
}

class _OfficeAccountCreationDrawerState
    extends State<_OfficeAccountCreationDrawer> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _nameFocus = FocusNode();
  final _emailFocus = FocusNode();
  final _passwordFocus = FocusNode();
  bool _creating = false;
  bool _passwordVisible = false;
  String? _formError;

  bool get _staff => widget.createStaff;

  String get _title =>
      _staff ? 'Add Office Staff Account' : 'Add Faculty Account';

  String get _description =>
      _staff
          ? 'Create a new office staff login for your office. They can sign in to manage tickets, knowledge base, and other office tools.'
          : 'Create a new faculty login. Faculty accounts can sign in and use faculty Knowledge Base tools. They do not open the office ticket console.';

  String get _nameHelper =>
      _staff
          ? "Use the staff member's complete name."
          : "Use the faculty member's complete name.";

  String get _submitLabel =>
      _staff ? 'Create Office Staff Account' : 'Create Faculty Account';

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _nameFocus.dispose();
    _emailFocus.dispose();
    _passwordFocus.dispose();
    super.dispose();
  }

  void _close() {
    if (_creating) return;
    Navigator.of(context).pop();
  }

  Future<void> _submit() async {
    if (_creating) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _creating = true;
      _formError = null;
    });
    try {
      final created = await widget.onCreate(
        fullName: _nameCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        password: _passwordCtrl.text,
      );
      if (!mounted) return;
      Navigator.of(context).pop(created);
    } catch (error) {
      if (!mounted) return;
      setState(() => _formError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  double _drawerWidth(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width < 560) return width;
    if (width < 900) return (width * 0.72).clamp(360.0, 520.0);
    return 480;
  }

  InputDecoration _fieldDecoration({
    required String hint,
    String? helper,
    Widget? suffixIcon,
  }) {
    const radius = BorderRadius.all(Radius.circular(10));
    return InputDecoration(
      hintText: hint,
      helperText: helper,
      helperMaxLines: 2,
      suffixIcon: suffixIcon,
      filled: true,
      fillColor: Colors.white,
      hintStyle: const TextStyle(
        color: Color(0xFF94A3B8),
        fontWeight: FontWeight.w500,
        fontSize: 14,
      ),
      helperStyle: const TextStyle(
        color: DesignTokens.muted,
        fontWeight: FontWeight.w500,
        fontSize: 12,
        height: 1.35,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      border: const OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Color(0xFFD9DEE7)),
      ),
      enabledBorder: const OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Color(0xFFD9DEE7)),
      ),
      focusedBorder: const OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: DesignTokens.maroon, width: 1.4),
      ),
      errorBorder: const OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Color(0xFFB91C1C)),
      ),
      focusedErrorBorder: const OutlineInputBorder(
        borderRadius: radius,
        borderSide: BorderSide(color: Color(0xFFB91C1C), width: 1.4),
      ),
    );
  }

  Widget _label(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Text(
            text,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w700,
              fontSize: 13,
            ),
          ),
          const Text(
            ' *',
            style: TextStyle(
              color: DesignTokens.maroon,
              fontWeight: FontWeight.w800,
              fontSize: 13,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final width = _drawerWidth(context);
    return Material(
      key: const Key('office-account-create-drawer'),
      color: Colors.white,
      elevation: 18,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      child: SizedBox(
        width: width,
        height: double.infinity,
        child: SafeArea(
          left: false,
          child: Padding(
            padding: EdgeInsets.only(
              bottom: MediaQuery.viewInsetsOf(context).bottom,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 18, 12, 0),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          _title,
                          style: const TextStyle(
                            color: DesignTokens.ink,
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                            height: 1.2,
                          ),
                        ),
                      ),
                      IconButton(
                        key: const Key('office-account-create-close'),
                        tooltip: 'Close',
                        onPressed: _creating ? null : _close,
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 0),
                  child: Text(
                    _description,
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      height: 1.45,
                    ),
                  ),
                ),
                Expanded(
                  child: Form(
                    key: _formKey,
                    child: ListView(
                      padding: const EdgeInsets.fromLTRB(24, 20, 24, 12),
                      children: [
                        _label('Full name'),
                        TextFormField(
                          key: const Key('office-account-create-name'),
                          controller: _nameCtrl,
                          focusNode: _nameFocus,
                          autofocus: true,
                          enabled: !_creating,
                          textInputAction: TextInputAction.next,
                          textCapitalization: TextCapitalization.words,
                          onFieldSubmitted: (_) => _emailFocus.requestFocus(),
                          decoration: _fieldDecoration(
                            hint: 'Enter full name',
                            helper: _nameHelper,
                          ),
                          validator:
                              (value) =>
                                  (value == null || value.trim().isEmpty)
                                      ? 'Enter a name.'
                                      : null,
                        ),
                        const SizedBox(height: 16),
                        _label('Email'),
                        TextFormField(
                          key: const Key('office-account-create-email'),
                          controller: _emailCtrl,
                          focusNode: _emailFocus,
                          enabled: !_creating,
                          keyboardType: TextInputType.emailAddress,
                          autocorrect: false,
                          textInputAction: TextInputAction.next,
                          onFieldSubmitted:
                              (_) => _passwordFocus.requestFocus(),
                          decoration: _fieldDecoration(
                            hint: 'Enter email address',
                            helper: 'Use a valid email address.',
                          ),
                          validator: (value) {
                            final text = value?.trim() ?? '';
                            if (text.isEmpty) return 'Enter an email.';
                            if (!text.contains('@')) {
                              return 'Enter a valid email.';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        _label('Temporary password'),
                        TextFormField(
                          key: const Key('office-account-create-password'),
                          controller: _passwordCtrl,
                          focusNode: _passwordFocus,
                          enabled: !_creating,
                          obscureText: !_passwordVisible,
                          textInputAction: TextInputAction.done,
                          onFieldSubmitted: (_) => _submit(),
                          decoration: _fieldDecoration(
                            hint: 'Enter temporary password',
                            helper:
                                'At least 10 characters, with a letter and a number.',
                            suffixIcon: IconButton(
                              key: const Key(
                                'office-account-create-password-toggle',
                              ),
                              tooltip:
                                  _passwordVisible
                                      ? 'Hide password'
                                      : 'Show password',
                              onPressed:
                                  _creating
                                      ? null
                                      : () => setState(
                                        () =>
                                            _passwordVisible =
                                                !_passwordVisible,
                                      ),
                              icon: Icon(
                                _passwordVisible
                                    ? Icons.visibility_off_outlined
                                    : Icons.visibility_outlined,
                              ),
                            ),
                          ),
                          validator: (value) {
                            final text = value ?? '';
                            if (text.length < 10) {
                              return 'Use at least 10 characters.';
                            }
                            if (!RegExp(r'[A-Za-z]').hasMatch(text) ||
                                !RegExp(r'\d').hasMatch(text)) {
                              return 'Include a letter and a number.';
                            }
                            return null;
                          },
                        ),
                        if (_formError != null) ...[
                          const SizedBox(height: 16),
                          Text(
                            _formError!,
                            style: const TextStyle(
                              color: Color(0xFFB91C1C),
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                const Divider(height: 1, color: Color(0xFFE8EDF3)),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 16, 24, 20),
                  child: Row(
                    children: [
                      Expanded(
                        child: OutlinedButton(
                          key: const Key('office-account-create-cancel'),
                          onPressed: _creating ? null : _close,
                          style: OutlinedButton.styleFrom(
                            foregroundColor: DesignTokens.maroon,
                            side: const BorderSide(color: DesignTokens.maroon),
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          child: const Text(
                            'Cancel',
                            style: TextStyle(fontWeight: FontWeight.w700),
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        flex: 2,
                        child: ElevatedButton(
                          key: const Key('office-account-create-submit'),
                          onPressed: _creating ? null : _submit,
                          style: ElevatedButton.styleFrom(
                            backgroundColor: DesignTokens.maroon,
                            foregroundColor: Colors.white,
                            disabledBackgroundColor: const Color(0xFF9A4A50),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 14,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(10),
                            ),
                          ),
                          child:
                              _creating
                                  ? const SizedBox(
                                    width: 18,
                                    height: 18,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: Colors.white,
                                    ),
                                  )
                                  : Text(
                                    _submitLabel,
                                    textAlign: TextAlign.center,
                                    maxLines: 2,
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w800,
                                      fontSize: 13,
                                    ),
                                  ),
                        ),
                      ),
                    ],
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
