part of 'admin_management_pages.dart';

const int _kUsersRolesPageSize = 7;

class AdminUsersRolesPage extends StatefulWidget {
  const AdminUsersRolesPage({
    super.key,
    this.debugUsers,
    this.debugOffices,
    this.debugError,
    this.debugCreateOfficeAccount,
    this.debugSetActive,
    this.debugResetPassword,
    this.debugDeleteUser,
  });

  @visibleForTesting
  final List<Map<String, dynamic>>? debugUsers;

  @visibleForTesting
  final List<Map<String, dynamic>>? debugOffices;

  @visibleForTesting
  final String? debugError;

  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required String fullName,
    required String email,
    required String password,
    required String officeId,
  })? debugCreateOfficeAccount;

  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required String userId,
    required bool isActive,
  })? debugSetActive;

  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required String userId,
    required String newPassword,
  })? debugResetPassword;

  @visibleForTesting
  final Future<void> Function(String userId)? debugDeleteUser;

  @override
  State<AdminUsersRolesPage> createState() => _AdminUsersRolesPageState();
}

class _AdminUsersRolesPageState extends State<AdminUsersRolesPage> {
  final List<_AdminUserEntry> _users = [];
  final List<_AdminOfficeEntry> _offices = [];
  final TextEditingController _searchCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  String _roleFilter = 'All';
  String _officeFilter = 'All';
  String _statusFilter = 'All';
  bool _requestedInitialLoad = false;
  int _page = 1;

  bool get _usesDebugSeed =>
      widget.debugUsers != null ||
      widget.debugOffices != null ||
      widget.debugError != null;

  @override
  void dispose() {
    _searchCtrl.dispose();
    super.dispose();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_requestedInitialLoad) return;
    if (_usesDebugSeed) {
      _requestedInitialLoad = true;
      _applyDebugSeed();
      return;
    }
    final auth = AuthScope.of(context);
    if (auth.role == 'admin') {
      _requestedInitialLoad = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _load();
      });
    }
  }

  void _applyDebugSeed() {
    final users = (widget.debugUsers ?? const [])
        .map(_AdminUserEntry.fromJson)
        .toList();
    final offices = (widget.debugOffices ?? const [])
        .map(_AdminOfficeEntry.fromJson)
        .toList()
      ..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    _users
      ..clear()
      ..addAll(users);
    _offices
      ..clear()
      ..addAll(offices);
    _error = widget.debugError;
    _loading = false;
    _page = _safePageFor(_filteredUsers.length);
  }

  Future<void> _load() async {
    if (_usesDebugSeed) {
      setState(_applyDebugSeed);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final users = await _loadAdminUsers(context);
      final offices = await _loadAdminOffices(context);
      if (!mounted) return;
      offices.sort(
        (a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()),
      );
      setState(() {
        _users
          ..clear()
          ..addAll(users);
        _offices
          ..clear()
          ..addAll(offices);
        _page = _safePageFor(_filteredUsers.length);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _replaceUser(_AdminUserEntry updated) {
    final index = _users.indexWhere((user) => user.id == updated.id);
    if (index == -1) {
      _users.insert(0, updated);
    } else {
      _users[index] = updated;
    }
  }

  Future<bool> _confirmAction({
    required String title,
    required String message,
    required String confirmLabel,
    Color? confirmColor,
  }) async {
    final confirmed = await showDialog<bool>(
      context: context,
      useRootNavigator: true,
      builder: (dialogContext) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            style: ElevatedButton.styleFrom(
              backgroundColor: confirmColor ?? DesignTokens.maroon,
              foregroundColor: Colors.white,
            ),
            child: Text(confirmLabel),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }

  Future<void> _createOfficeAccount({
    required String fullName,
    required String email,
    required String password,
    required String officeId,
  }) async {
    final created = widget.debugCreateOfficeAccount != null
        ? _AdminUserEntry.fromJson(
            await widget.debugCreateOfficeAccount!(
              fullName: fullName,
              email: email,
              password: password,
              officeId: officeId,
            ),
          )
        : await _createOfficeAccountRequest(
            context,
            fullName: fullName,
            email: email,
            password: password,
            officeId: officeId,
          );
    if (_usesDebugSeed) {
      setState(() => _replaceUser(created));
    } else {
      await _load();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Office account created for ${created.email}')),
    );
  }

  Future<void> _setActive(_AdminUserEntry user, {required bool isActive}) async {
    final updated = widget.debugSetActive != null
        ? _AdminUserEntry.fromJson(
            await widget.debugSetActive!(
              userId: user.id,
              isActive: isActive,
            ),
          )
        : await _setUserActiveRequest(
            context,
            userId: user.id,
            isActive: isActive,
          );
    if (!mounted) return;
    setState(() => _replaceUser(updated));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          isActive
              ? 'Re-enabled ${updated.email}'
              : 'Disabled ${updated.email}',
        ),
      ),
    );
  }

  Future<void> _resetPassword(
    _AdminUserEntry user, {
    required String newPassword,
  }) async {
    final updated = widget.debugResetPassword != null
        ? _AdminUserEntry.fromJson(
            await widget.debugResetPassword!(
              userId: user.id,
              newPassword: newPassword,
            ),
          )
        : await _resetUserPasswordRequest(
            context,
            userId: user.id,
            newPassword: newPassword,
          );
    if (!mounted) return;
    setState(() => _replaceUser(updated));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Password reset for ${updated.email}')),
    );
  }

  Future<void> _deleteUser(_AdminUserEntry user) async {
    final confirmed = await _confirmAction(
      title: 'Delete account?',
      message:
          'Delete ${user.fullName} (${user.email})? This cannot be undone.',
      confirmLabel: 'Delete',
      confirmColor: const Color(0xFFB91C1C),
    );
    if (!confirmed) return;
    if (widget.debugDeleteUser != null) {
      await widget.debugDeleteUser!(user.id);
    } else {
      await _deleteOfficeAccountRequest(context, userId: user.id);
    }
    if (!mounted) return;
    setState(() {
      _users.removeWhere((item) => item.id == user.id);
      _page = _safePageFor(_filteredUsers.length);
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Account deleted: ${user.email}')),
    );
  }

  Future<void> _openAddAccount() async {
    await showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Add account',
      barrierColor: Colors.black.withValues(alpha: 0.32),
      transitionDuration: const Duration(milliseconds: 240),
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        return Align(
          alignment: Alignment.centerRight,
          child: _UsersRolesAddAccountDrawer(
            offices: List.of(_offices),
            onClose: () => Navigator.of(dialogContext).pop(),
            onCreate: ({
              required fullName,
              required email,
              required password,
              required officeId,
            }) async {
              await _createOfficeAccount(
                fullName: fullName,
                email: email,
                password: password,
                officeId: officeId,
              );
              if (dialogContext.mounted) {
                Navigator.of(dialogContext).pop();
              }
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
  }

  Future<void> _openView(_AdminUserEntry user) async {
    final selectedId = user.id;
    await showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Account details',
      barrierColor: Colors.black.withValues(alpha: 0.32),
      transitionDuration: const Duration(milliseconds: 240),
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            _AdminUserEntry? current;
            for (final item in _users) {
              if (item.id == selectedId) {
                current = item;
                break;
              }
            }
            if (current == null) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                if (dialogContext.mounted) {
                  Navigator.of(dialogContext).pop();
                }
              });
              return const SizedBox.shrink();
            }
            final width = MediaQuery.sizeOf(context).width;
            return Align(
              alignment: Alignment.centerRight,
              child: _UsersRolesManageDrawer(
                user: current,
                currentUserId: AuthScope.of(context).currentUser?.id,
                activeAdminCount: _users
                    .where((item) => item.role == 'admin' && item.isActive)
                    .length,
                width: width < 560 ? width : 420,
                onClose: () => Navigator.of(dialogContext).pop(),
                onSetActive: (isActive) async {
                  await _setActive(current!, isActive: isActive);
                  setDialogState(() {});
                },
                onResetPassword: (password) async {
                  await _resetPassword(current!, newPassword: password);
                  setDialogState(() {});
                },
                onDelete: () async {
                  await _deleteUser(current!);
                  setDialogState(() {});
                },
              ),
            );
          },
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
  }

  List<_AdminUserEntry> get _filteredUsers {
    return _users.where((user) {
      if (_roleFilter != 'All' && user.role != _roleFilter) return false;
      if (_statusFilter == 'active' && !user.isActive) return false;
      if (_statusFilter == 'inactive' && user.isActive) return false;
      if (_officeFilter != 'All' && !_matchesOffice(user, _officeFilter)) {
        return false;
      }
      return user.matchesNameOrEmail(_searchCtrl.text);
    }).toList();
  }

  bool _matchesOffice(_AdminUserEntry user, String officeName) {
    if ((user.officeName ?? '').trim() == officeName) return true;
    for (final office in _offices) {
      if (office.id == user.officeId && office.name == officeName) {
        return true;
      }
    }
    return false;
  }

  List<String> _officeOptions() {
    final names = <String>{
      ..._offices.map((office) => office.name.trim()).where((name) => name.isNotEmpty),
      ..._users
          .map((user) => (user.officeName ?? '').trim())
          .where((name) => name.isNotEmpty),
    }.toList()
      ..sort((a, b) => a.toLowerCase().compareTo(b.toLowerCase()));
    return names;
  }

  int _pageCountFor(int count) {
    if (count <= 0) return 1;
    return ((count + _kUsersRolesPageSize - 1) / _kUsersRolesPageSize).floor();
  }

  int _safePageFor(int count) {
    return _page.clamp(1, _pageCountFor(count));
  }

  List<_AdminUserEntry> get _pageUsers {
    final filtered = _filteredUsers;
    final page = _safePageFor(filtered.length);
    final start = (page - 1) * _kUsersRolesPageSize;
    if (start >= filtered.length) return const [];
    final end = (start + _kUsersRolesPageSize).clamp(0, filtered.length);
    return filtered.sublist(start, end);
  }

  void _resetFilters() {
    setState(() {
      _searchCtrl.clear();
      _roleFilter = 'All';
      _officeFilter = 'All';
      _statusFilter = 'All';
      _page = 1;
    });
  }

  int get _studentCount =>
      _users.where((user) => user.role == 'student').length;

  int get _facultyCount =>
      _users.where((user) => user.role == 'faculty').length;

  int get _officeStaffCount =>
      _users.where((user) => user.role == 'office').length;

  int get _adminCount => _users.where((user) => user.role == 'admin').length;

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredUsers;
    final pageUsers = _pageUsers;
    final page = _safePageFor(filtered.length);
    final pageCount = _pageCountFor(filtered.length);

    return AdminScaffold(
      current: StudentNavItem.adminUsersRoles,
      title: 'Users & Roles',
      description:
          'Manage user accounts, roles, and office access for the system.',
      fillBody: true,
      showHeader: false,
      child: ColoredBox(
        color: DesignTokens.adminSurface,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 900;
            final compact = constraints.maxWidth < 900;
            return Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1180),
                child: ListView(
                  key: const Key('admin-users-roles-page'),
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    28,
                  ),
                  children: [
                    if (_loading) const LinearProgressIndicator(minHeight: 3),
                    if (_error != null) ...[
                      KeyedSubtree(
                        key: const Key('admin-users-roles-error'),
                        child: _AdminNotice(
                          icon: Icons.info_outline_rounded,
                          message: _error!,
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    _UsersRolesHeader(
                      stacked: constraints.maxWidth < 560,
                      onAdd: _loading ? null : _openAddAccount,
                    ),
                    const SizedBox(height: 16),
                    _UsersRolesStatsRow(
                      students: _studentCount,
                      faculty: _facultyCount,
                      officeStaff: _officeStaffCount,
                      admins: _adminCount,
                    ),
                    const SizedBox(height: 14),
                    _UsersRolesFilterBar(
                      searchCtrl: _searchCtrl,
                      roleFilter: _roleFilter,
                      officeFilter: _officeFilter,
                      statusFilter: _statusFilter,
                      officeOptions: _officeOptions(),
                      stacked: constraints.maxWidth < 980,
                      onSearchChanged: (_) => setState(() => _page = 1),
                      onRoleChanged: (value) {
                        setState(() {
                          _roleFilter = value;
                          _page = 1;
                        });
                      },
                      onOfficeChanged: (value) {
                        setState(() {
                          _officeFilter = value;
                          _page = 1;
                        });
                      },
                      onStatusChanged: (value) {
                        setState(() {
                          _statusFilter = value;
                          _page = 1;
                        });
                      },
                      onClear: _resetFilters,
                    ),
                    const SizedBox(height: 14),
                    if (_loading && _users.isEmpty)
                      const _UsersRolesEmpty(
                        title: 'Loading accounts',
                        message: 'Fetching user accounts for this workspace.',
                      )
                    else if (filtered.isEmpty)
                      _UsersRolesEmpty(
                        title: _users.isEmpty
                            ? 'No accounts yet'
                            : 'No matching accounts',
                        message: _users.isEmpty
                            ? 'User accounts will appear here after they are created or registered.'
                            : 'Try changing the search text, role, office, or status filter.',
                      )
                    else
                      _UsersRolesTable(
                        users: pageUsers,
                        compact: compact,
                        onView: _openView,
                      ),
                    if (filtered.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      _UsersRolesPager(
                        page: page,
                        pageCount: pageCount,
                        pageSize: _kUsersRolesPageSize,
                        filteredCount: filtered.length,
                        onPageChanged: (next) => setState(() => _page = next),
                      ),
                    ],
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _UsersRolesHeader extends StatelessWidget {
  const _UsersRolesHeader({
    required this.stacked,
    required this.onAdd,
  });

  final bool stacked;
  final VoidCallback? onAdd;

  @override
  Widget build(BuildContext context) {
    const copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Users & Roles',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Manage user accounts, roles, and office access for the system.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    final add = ElevatedButton(
      key: const Key('admin-users-add'),
      onPressed: onAdd,
      style: ElevatedButton.styleFrom(
        backgroundColor: DesignTokens.maroon,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      child: const Text(
        '+ Add Account',
        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
      ),
    );
    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          copy,
          const SizedBox(height: 12),
          Align(alignment: Alignment.centerLeft, child: add),
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Expanded(child: copy),
        const SizedBox(width: 12),
        add,
      ],
    );
  }
}

class _UsersRolesStatsRow extends StatelessWidget {
  const _UsersRolesStatsRow({
    required this.students,
    required this.faculty,
    required this.officeStaff,
    required this.admins,
  });

  final int students;
  final int faculty;
  final int officeStaff;
  final int admins;

  @override
  Widget build(BuildContext context) {
    final stats = [
      (
        label: 'Students',
        value: '$students',
        key: 'admin-users-stat-students',
        background: const Color(0xFFF8EDED),
        valueColor: DesignTokens.maroon,
      ),
      (
        label: 'Faculty',
        value: '$faculty',
        key: 'admin-users-stat-faculty',
        background: const Color(0xFFFFF4E8),
        valueColor: const Color(0xFFC2410C),
      ),
      (
        label: 'Office Staff',
        value: '$officeStaff',
        key: 'admin-users-stat-office',
        background: const Color(0xFFEFF6FF),
        valueColor: const Color(0xFF1D4ED8),
      ),
      (
        label: 'Admins',
        value: '$admins',
        key: 'admin-users-stat-admins',
        background: const Color(0xFFECFDF3),
        valueColor: const Color(0xFF15803D),
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final columns = width >= 900
            ? 4
            : width >= 560
                ? 2
                : 1;
        const gap = 12.0;
        final cardWidth = columns == 1
            ? width
            : (width - gap * (columns - 1)) / columns;
        return Wrap(
          spacing: gap,
          runSpacing: gap,
          children: [
            for (final stat in stats)
              SizedBox(
                width: cardWidth,
                child: Container(
                  key: Key(stat.key),
                  padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
                  decoration: BoxDecoration(
                    color: stat.background,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: DesignTokens.border),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        stat.value,
                        style: TextStyle(
                          color: stat.valueColor,
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          height: 1,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        stat.label,
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class _UsersRolesFilterBar extends StatelessWidget {
  const _UsersRolesFilterBar({
    required this.searchCtrl,
    required this.roleFilter,
    required this.officeFilter,
    required this.statusFilter,
    required this.officeOptions,
    required this.stacked,
    required this.onSearchChanged,
    required this.onRoleChanged,
    required this.onOfficeChanged,
    required this.onStatusChanged,
    required this.onClear,
  });

  final TextEditingController searchCtrl;
  final String roleFilter;
  final String officeFilter;
  final String statusFilter;
  final List<String> officeOptions;
  final bool stacked;
  final ValueChanged<String> onSearchChanged;
  final ValueChanged<String> onRoleChanged;
  final ValueChanged<String> onOfficeChanged;
  final ValueChanged<String> onStatusChanged;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final offices = ['All', ...officeOptions];
    final search = _UsersRolesSearchField(
      controller: searchCtrl,
      onChanged: onSearchChanged,
    );
    final filters = [
      _UsersRolesFilterDropdown(
        fieldKey: const Key('admin-users-role-filter'),
        label: 'Role',
        value: roleFilter,
        values: const ['All', 'student', 'faculty', 'office', 'admin'],
        displayLabel: _usersRolesRoleFilterLabel,
        onChanged: onRoleChanged,
      ),
      _UsersRolesFilterDropdown(
        fieldKey: const Key('admin-users-office-filter'),
        label: 'Office',
        value: offices.contains(officeFilter) ? officeFilter : 'All',
        values: offices,
        displayLabel: (value) => value == 'All' ? 'All Offices' : value,
        onChanged: onOfficeChanged,
      ),
      _UsersRolesFilterDropdown(
        fieldKey: const Key('admin-users-status-filter'),
        label: 'Status',
        value: statusFilter,
        values: const ['All', 'active', 'inactive'],
        displayLabel: _usersRolesStatusFilterLabel,
        onChanged: onStatusChanged,
      ),
    ];
    final clear = OutlinedButton(
      key: const Key('admin-users-clear-filters'),
      onPressed: onClear,
      style: OutlinedButton.styleFrom(
        foregroundColor: DesignTokens.maroon,
        side: const BorderSide(color: Color(0xFFD7B4B6)),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      child: const Text(
        'Clear Filters',
        style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
      ),
    );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: stacked
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                search,
                const SizedBox(height: 10),
                ...filters.map(
                  (filter) => Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: filter,
                  ),
                ),
                Align(alignment: Alignment.centerLeft, child: clear),
              ],
            )
          : Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(flex: 3, child: search),
                const SizedBox(width: 12),
                for (var i = 0; i < filters.length; i++) ...[
                  Expanded(child: filters[i]),
                  const SizedBox(width: 12),
                ],
                Padding(
                  padding: const EdgeInsets.only(bottom: 1),
                  child: clear,
                ),
              ],
            ),
    );
  }
}

class _UsersRolesSearchField extends StatelessWidget {
  const _UsersRolesSearchField({
    required this.controller,
    required this.onChanged,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Search',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          key: const Key('admin-users-search'),
          controller: controller,
          onChanged: onChanged,
          decoration: InputDecoration(
            hintText: 'Search by name or email...',
            prefixIcon: const Icon(Icons.search_rounded, size: 20),
            suffixIcon: controller.text.isEmpty
                ? null
                : IconButton(
                    onPressed: () {
                      controller.clear();
                      onChanged('');
                    },
                    icon: const Icon(Icons.clear_rounded),
                  ),
            isDense: true,
            filled: true,
            fillColor: Colors.white,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 12,
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
              borderSide: const BorderSide(
                color: DesignTokens.maroon,
                width: 1.2,
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _UsersRolesFilterDropdown extends StatelessWidget {
  const _UsersRolesFilterDropdown({
    required this.fieldKey,
    required this.label,
    required this.value,
    required this.values,
    required this.displayLabel,
    required this.onChanged,
  });

  final Key fieldKey;
  final String label;
  final String value;
  final List<String> values;
  final String Function(String value) displayLabel;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 6),
        DropdownButtonFormField<String>(
          key: fieldKey,
          value: values.contains(value) ? value : values.first,
          isExpanded: true,
          decoration: InputDecoration(
            isDense: true,
            filled: true,
            fillColor: Colors.white,
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 12,
              vertical: 12,
            ),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(10),
              borderSide: const BorderSide(color: DesignTokens.border),
            ),
          ),
          items: values
              .map(
                (item) => DropdownMenuItem(
                  value: item,
                  child: Text(
                    displayLabel(item),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              )
              .toList(),
          onChanged: (next) {
            if (next != null) onChanged(next);
          },
        ),
      ],
    );
  }
}

class _UsersRolesEmpty extends StatelessWidget {
  const _UsersRolesEmpty({
    required this.title,
    required this.message,
  });

  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('admin-users-empty'),
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: DesignTokens.muted),
          ),
        ],
      ),
    );
  }
}

class _UsersRolesTable extends StatelessWidget {
  const _UsersRolesTable({
    required this.users,
    required this.compact,
    required this.onView,
  });

  final List<_AdminUserEntry> users;
  final bool compact;
  final ValueChanged<_AdminUserEntry> onView;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        children: [
          if (!compact) const _UsersRolesTableHeader(),
          for (var i = 0; i < users.length; i++) ...[
            if (i > 0 || !compact)
              const Divider(height: 1, color: DesignTokens.border),
            compact
                ? _UsersRolesCardRow(
                    user: users[i],
                    onView: () => onView(users[i]),
                  )
                : _UsersRolesTableRow(
                    user: users[i],
                    onView: () => onView(users[i]),
                  ),
          ],
        ],
      ),
    );
  }
}

class _UsersRolesTableHeader extends StatelessWidget {
  const _UsersRolesTableHeader();

  @override
  Widget build(BuildContext context) {
    const style = TextStyle(
      color: DesignTokens.muted,
      fontSize: 11,
      fontWeight: FontWeight.w800,
      letterSpacing: 0.4,
    );
    return const Padding(
      padding: EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Row(
        children: [
          Expanded(flex: 3, child: Text('NAME', style: style)),
          Expanded(flex: 4, child: Text('EMAIL', style: style)),
          Expanded(flex: 2, child: Text('ROLE', style: style)),
          Expanded(flex: 3, child: Text('OFFICE', style: style)),
          Expanded(flex: 2, child: Text('STATUS', style: style)),
          SizedBox(
            width: 56,
            child: Text('ACTIONS', style: style, textAlign: TextAlign.right),
          ),
        ],
      ),
    );
  }
}

class _UsersRolesTableRow extends StatelessWidget {
  const _UsersRolesTableRow({
    required this.user,
    required this.onView,
  });

  final _AdminUserEntry user;
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('admin-users-row-${user.id}'),
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: Text(
              _usersRolesDisplayName(user),
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
            flex: 4,
            child: Tooltip(
              message: user.email,
              child: Text(
                user.email,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Align(
              alignment: Alignment.centerLeft,
              child: _UsersRolesRolePill(role: user.role, userId: user.id),
            ),
          ),
          Expanded(
            flex: 3,
            child: Text(
              _usersRolesOfficeLabel(user),
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
              child: _UsersRolesStatusPill(
                active: user.isActive,
                userId: user.id,
              ),
            ),
          ),
          SizedBox(
            width: 56,
            child: Align(
              alignment: Alignment.centerRight,
              child: _UsersRolesViewLink(
                key: Key('admin-users-view-${user.id}'),
                onTap: onView,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _UsersRolesCardRow extends StatelessWidget {
  const _UsersRolesCardRow({
    required this.user,
    required this.onView,
  });

  final _AdminUserEntry user;
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    return Padding(
      key: Key('admin-users-row-${user.id}'),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _usersRolesDisplayName(user),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 14,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            user.email,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            children: [
              _UsersRolesRolePill(role: user.role, userId: user.id),
              _UsersRolesStatusPill(active: user.isActive, userId: user.id),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            _usersRolesOfficeLabel(user),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          _UsersRolesViewLink(
            key: Key('admin-users-view-${user.id}'),
            onTap: onView,
          ),
        ],
      ),
    );
  }
}

class _UsersRolesViewLink extends StatelessWidget {
  const _UsersRolesViewLink({
    super.key,
    required this.onTap,
  });

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: const Padding(
        padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
        child: Text(
          'View',
          style: TextStyle(
            color: DesignTokens.maroon,
            fontWeight: FontWeight.w800,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}

class _UsersRolesRolePill extends StatelessWidget {
  const _UsersRolesRolePill({
    required this.role,
    required this.userId,
  });

  final String role;
  final String userId;

  @override
  Widget build(BuildContext context) {
    final colors = switch (role) {
      'student' => (const Color(0xFFFEE2E2), const Color(0xFFB91C1C)),
      'faculty' => (const Color(0xFFFEF3C7), const Color(0xFFB45309)),
      'office' => (const Color(0xFFDBEAFE), const Color(0xFF1D4ED8)),
      'admin' => (const Color(0xFFEDE9FE), const Color(0xFF6D28D9)),
      _ => (const Color(0xFFF1F5F9), DesignTokens.muted),
    };
    return Container(
      key: Key('admin-users-role-$userId'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: colors.$1,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        _usersRolesRoleLabel(role),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: colors.$2,
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _UsersRolesStatusPill extends StatelessWidget {
  const _UsersRolesStatusPill({
    required this.active,
    required this.userId,
  });

  final bool active;
  final String userId;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: Key('admin-users-status-$userId'),
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: active ? const Color(0xFFDCFCE7) : const Color(0xFFFEE2E2),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        active ? 'Active' : 'Inactive',
        style: TextStyle(
          color: active ? const Color(0xFF15803D) : const Color(0xFFB91C1C),
          fontSize: 11,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _UsersRolesPager extends StatelessWidget {
  const _UsersRolesPager({
    required this.page,
    required this.pageCount,
    required this.pageSize,
    required this.filteredCount,
    required this.onPageChanged,
  });

  final int page;
  final int pageCount;
  final int pageSize;
  final int filteredCount;
  final ValueChanged<int> onPageChanged;

  @override
  Widget build(BuildContext context) {
    final start = filteredCount == 0 ? 0 : ((page - 1) * pageSize) + 1;
    final end = (page * pageSize).clamp(0, filteredCount);
    final pages = _usersRolesVisiblePages(page, pageCount);
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 720;
        return Wrap(
          key: const Key('admin-users-pager'),
          spacing: 4,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          alignment: compact ? WrapAlignment.start : WrapAlignment.spaceBetween,
          children: [
            Text(
              'Showing $start–$end of $filteredCount accounts',
              style: const TextStyle(
                color: DesignTokens.muted,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
            Wrap(
              spacing: 2,
              runSpacing: 4,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                TextButton(
                  onPressed: page > 1 ? () => onPageChanged(page - 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 8,
                    ),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Previous'),
                ),
                for (final item in pages)
                  item == null
                      ? const Padding(
                          padding: EdgeInsets.symmetric(horizontal: 6),
                          child: Text(
                            '…',
                            style: TextStyle(
                              color: DesignTokens.muted,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        )
                      : Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 2),
                          child: Material(
                            color: item == page
                                ? DesignTokens.maroon
                                : Colors.white,
                            borderRadius: BorderRadius.circular(8),
                            child: InkWell(
                              onTap: () => onPageChanged(item),
                              borderRadius: BorderRadius.circular(8),
                              child: Container(
                                width: 32,
                                height: 32,
                                alignment: Alignment.center,
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(8),
                                  border: Border.all(
                                    color: item == page
                                        ? DesignTokens.maroon
                                        : DesignTokens.border,
                                  ),
                                ),
                                child: Text(
                                  '$item',
                                  style: TextStyle(
                                    color: item == page
                                        ? Colors.white
                                        : DesignTokens.ink,
                                    fontWeight: FontWeight.w800,
                                    fontSize: 12,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                TextButton(
                  onPressed:
                      page < pageCount ? () => onPageChanged(page + 1) : null,
                  style: TextButton.styleFrom(
                    minimumSize: Size.zero,
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 8,
                    ),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Next'),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}

class _UsersRolesManageDrawer extends StatefulWidget {
  const _UsersRolesManageDrawer({
    required this.user,
    required this.currentUserId,
    required this.activeAdminCount,
    required this.width,
    required this.onClose,
    required this.onSetActive,
    required this.onResetPassword,
    required this.onDelete,
  });

  final _AdminUserEntry user;
  final String? currentUserId;
  final int activeAdminCount;
  final double width;
  final VoidCallback onClose;
  final Future<void> Function(bool isActive) onSetActive;
  final Future<void> Function(String password) onResetPassword;
  final Future<void> Function() onDelete;

  @override
  State<_UsersRolesManageDrawer> createState() =>
      _UsersRolesManageDrawerState();
}

class _UsersRolesManageDrawerState extends State<_UsersRolesManageDrawer> {
  final _passwordCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _passwordCtrl.dispose();
    super.dispose();
  }

  bool get _isSelf =>
      widget.currentUserId != null && widget.currentUserId == widget.user.id;

  bool get _isLastActiveAdmin =>
      widget.user.role == 'admin' &&
      widget.user.isActive &&
      widget.activeAdminCount <= 1;

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _submitPassword() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final password = _passwordCtrl.text;
    await _run(() async {
      await widget.onResetPassword(password);
      if (!mounted) return;
      _passwordCtrl.clear();
    });
  }

  @override
  Widget build(BuildContext context) {
    final user = widget.user;
    return Material(
      key: const Key('admin-users-manage-drawer'),
      color: Colors.white,
      elevation: 18,
      shadowColor: Colors.black.withValues(alpha: 0.18),
      child: SizedBox(
        width: widget.width,
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
                  padding: const EdgeInsets.fromLTRB(20, 16, 8, 0),
                  child: Row(
                    children: [
                      const Expanded(
                        child: Text(
                          'Account Details',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                            color: DesignTokens.ink,
                          ),
                        ),
                      ),
                      IconButton(
                        key: const Key('admin-users-manage-close'),
                        onPressed: _busy ? null : widget.onClose,
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
                    children: [
                      _UsersRolesDetailRow(
                        label: 'Name',
                        value: _usersRolesDisplayName(user),
                      ),
                      _UsersRolesDetailRow(label: 'Email', value: user.email),
                      _UsersRolesDetailRow(
                        label: 'Role',
                        value: _usersRolesRoleLabel(user.role),
                      ),
                      _UsersRolesDetailRow(
                        label: 'Office',
                        value: _usersRolesOfficeLabel(user),
                      ),
                      _UsersRolesDetailRow(
                        label: 'Status',
                        value: user.isActive ? 'Active' : 'Inactive',
                      ),
                      _UsersRolesDetailRow(
                        label: 'Created date',
                        value: user.createdAt == null
                            ? '—'
                            : _adminFormatAssignedDate(user.createdAt!),
                      ),
                      const SizedBox(height: 18),
                      const Text(
                        'Account management',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      if (_error != null) ...[
                        Text(
                          _error!,
                          style: const TextStyle(color: Color(0xFFB91C1C)),
                        ),
                        const SizedBox(height: 8),
                      ],
                      ElevatedButton(
                        key: const Key('admin-users-toggle-active'),
                        onPressed: _busy || _isSelf
                            ? null
                            : () => _run(
                                  () => widget.onSetActive(!user.isActive),
                                ),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: DesignTokens.maroon,
                          foregroundColor: Colors.white,
                        ),
                        child: Text(
                          user.isActive ? 'Deactivate account' : 'Activate account',
                        ),
                      ),
                      if (_isSelf)
                        const Padding(
                          padding: EdgeInsets.only(top: 6),
                          child: Text(
                            'You cannot disable your own account.',
                            style: TextStyle(
                              color: DesignTokens.muted,
                              fontSize: 12,
                            ),
                          ),
                        ),
                      const SizedBox(height: 16),
                      const Text(
                        'Reset password',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Form(
                        key: _formKey,
                        child: Column(
                          children: [
                            TextFormField(
                              key: const Key('admin-users-reset-password'),
                              controller: _passwordCtrl,
                              obscureText: true,
                              enabled: !_busy,
                              decoration: const InputDecoration(
                                labelText: 'New password',
                                helperText:
                                    'At least 10 characters with a letter and number.',
                              ),
                              validator: _usersRolesPasswordValidator,
                            ),
                            const SizedBox(height: 10),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: OutlinedButton(
                                key: const Key('admin-users-reset-submit'),
                                onPressed: _busy ? null : _submitPassword,
                                child: const Text('Reset password'),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 18),
                      OutlinedButton(
                        key: const Key('admin-users-delete'),
                        onPressed: _busy || _isSelf || _isLastActiveAdmin
                            ? null
                            : () => _run(widget.onDelete),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: const Color(0xFFB91C1C),
                          side: const BorderSide(color: Color(0xFFB91C1C)),
                        ),
                        child: const Text('Delete account'),
                      ),
                      if (_isSelf || _isLastActiveAdmin)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(
                            _isSelf
                                ? 'You cannot delete your own account.'
                                : 'Cannot delete the last active admin account.',
                            style: const TextStyle(
                              color: DesignTokens.muted,
                              fontSize: 12,
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

class _UsersRolesDetailRow extends StatelessWidget {
  const _UsersRolesDetailRow({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 11,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w700,
              fontSize: 14,
            ),
          ),
        ],
      ),
    );
  }
}

class _UsersRolesAddAccountDrawer extends StatefulWidget {
  const _UsersRolesAddAccountDrawer({
    required this.offices,
    required this.onClose,
    required this.onCreate,
  });

  final List<_AdminOfficeEntry> offices;
  final VoidCallback onClose;
  final Future<void> Function({
    required String fullName,
    required String email,
    required String password,
    required String officeId,
  }) onCreate;

  @override
  State<_UsersRolesAddAccountDrawer> createState() =>
      _UsersRolesAddAccountDrawerState();
}

class _UsersRolesAddAccountDrawerState
    extends State<_UsersRolesAddAccountDrawer> {
  static const _supportedType = 'office';

  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  String? _officeId;
  bool _creating = false;
  String? _formError;

  @override
  void initState() {
    super.initState();
    _officeId = widget.offices.isNotEmpty ? widget.offices.first.id : null;
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    super.dispose();
  }

  double _drawerWidth(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    if (width < 560) return width;
    if (width < 900) return (width * 0.72).clamp(360.0, 520.0);
    return 480;
  }

  Future<void> _submit() async {
    if (_creating) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;
    if (_officeId == null || _officeId!.isEmpty) {
      setState(() => _formError = 'Select an office.');
      return;
    }
    setState(() {
      _creating = true;
      _formError = null;
    });
    try {
      await widget.onCreate(
        fullName: _nameCtrl.text.trim(),
        email: _emailCtrl.text.trim(),
        password: _passwordCtrl.text,
        officeId: _officeId!,
      );
    } catch (error) {
      if (!mounted) return;
      setState(() => _formError = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final width = _drawerWidth(context);
    return Material(
      key: const Key('admin-users-add-drawer'),
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
                    children: [
                      const Expanded(
                        child: Text(
                          'Add Account',
                          style: TextStyle(
                            color: DesignTokens.ink,
                            fontSize: 22,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                      IconButton(
                        key: const Key('admin-users-add-close'),
                        onPressed: _creating ? null : widget.onClose,
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.fromLTRB(24, 8, 24, 0),
                  child: Text(
                    'Admin can create office staff logins and assign them to a campus office. Faculty and student accounts use their existing workflows.',
                    style: TextStyle(
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
                        const Text(
                          'Account type',
                          style: TextStyle(
                            color: DesignTokens.ink,
                            fontWeight: FontWeight.w700,
                            fontSize: 13,
                          ),
                        ),
                        const SizedBox(height: 8),
                        DropdownButtonFormField<String>(
                          key: const Key('admin-users-add-type'),
                          value: _supportedType,
                          items: const [
                            DropdownMenuItem(
                              value: _supportedType,
                              child: Text('Office Staff'),
                            ),
                          ],
                          onChanged: (_) {},
                          decoration: const InputDecoration(
                            isDense: true,
                          ),
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          key: const Key('admin-users-add-name'),
                          controller: _nameCtrl,
                          enabled: !_creating,
                          decoration: const InputDecoration(
                            labelText: 'Full name',
                          ),
                          validator: (value) =>
                              (value == null || value.trim().isEmpty)
                                  ? 'Enter a name.'
                                  : null,
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          key: const Key('admin-users-add-email'),
                          controller: _emailCtrl,
                          enabled: !_creating,
                          decoration: const InputDecoration(labelText: 'Email'),
                          validator: (value) {
                            final text = value?.trim() ?? '';
                            if (text.isEmpty) return 'Enter an email.';
                            if (!text.contains('@')) {
                              return 'Enter a valid email.';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                        TextFormField(
                          key: const Key('admin-users-add-password'),
                          controller: _passwordCtrl,
                          obscureText: true,
                          enabled: !_creating,
                          decoration: const InputDecoration(
                            labelText: 'Temporary password',
                            helperText:
                                'At least 10 characters with a letter and number.',
                          ),
                          validator: _usersRolesPasswordValidator,
                        ),
                        const SizedBox(height: 12),
                        DropdownButtonFormField<String>(
                          key: const Key('admin-users-add-office'),
                          value: widget.offices.any((office) => office.id == _officeId)
                              ? _officeId
                              : null,
                          isExpanded: true,
                          decoration: const InputDecoration(labelText: 'Office'),
                          items: widget.offices
                              .map(
                                (office) => DropdownMenuItem(
                                  value: office.id,
                                  child: Text(
                                    office.name,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              )
                              .toList(),
                          onChanged: _creating
                              ? null
                              : (value) => setState(() => _officeId = value),
                          validator: (value) =>
                              (value == null || value.isEmpty)
                                  ? 'Select an office.'
                                  : null,
                        ),
                        if (_formError != null) ...[
                          const SizedBox(height: 12),
                          Text(
                            _formError!,
                            style: const TextStyle(color: Color(0xFFB91C1C)),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 8, 24, 20),
                  child: ElevatedButton(
                    key: const Key('admin-users-add-submit'),
                    onPressed: _creating ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: DesignTokens.maroon,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: _creating
                        ? const SizedBox(
                            width: 18,
                            height: 18,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text('Create office staff account'),
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

String _usersRolesDisplayName(_AdminUserEntry user) {
  final name = user.fullName.trim();
  return name.isEmpty ? '—' : name;
}

String _usersRolesOfficeLabel(_AdminUserEntry user) {
  final office = (user.officeName ?? '').trim();
  return office.isEmpty ? '—' : office;
}

String _usersRolesRoleLabel(String role) {
  switch (role.toLowerCase()) {
    case 'student':
      return 'Student';
    case 'faculty':
      return 'Faculty';
    case 'office':
      return 'Office Staff';
    case 'admin':
      return 'Admin';
    default:
      return _adminTitleCase(role);
  }
}

String _usersRolesRoleFilterLabel(String value) {
  if (value == 'All') return 'All Roles';
  return _usersRolesRoleLabel(value);
}

String _usersRolesStatusFilterLabel(String value) {
  switch (value) {
    case 'active':
      return 'Active';
    case 'inactive':
      return 'Inactive';
    default:
      return 'All Statuses';
  }
}

String? _usersRolesPasswordValidator(String? value) {
  final text = value ?? '';
  if (text.length < 10) return 'Use at least 10 characters.';
  if (!RegExp(r'[A-Za-z]').hasMatch(text) || !RegExp(r'\d').hasMatch(text)) {
    return 'Include a letter and a number.';
  }
  return null;
}

List<int?> _usersRolesVisiblePages(int current, int total) {
  if (total <= 7) return [for (var i = 1; i <= total; i++) i];
  if (current <= 3) return [1, 2, 3, null, total];
  if (current >= total - 2) return [1, null, total - 2, total - 1, total];
  return [1, null, current - 1, current, current + 1, null, total];
}
