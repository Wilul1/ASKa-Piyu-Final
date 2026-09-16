part of 'admin_management_pages.dart';

const int _kOfficePageSize = 7;

class AdminOfficesPage extends StatefulWidget {
  const AdminOfficesPage({
    super.key,
    this.debugOffices,
    this.debugOfficeUsers,
    this.debugStats,
    this.debugCreateOffice,
    this.debugDeleteOffice,
    this.debugCreateStaff,
    this.debugDeleteStaff,
  });

  @visibleForTesting
  final List<Map<String, dynamic>>? debugOffices;

  @visibleForTesting
  final List<Map<String, dynamic>>? debugOfficeUsers;

  @visibleForTesting
  final Map<String, dynamic>? debugStats;

  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required String name,
    required String serviceCategory,
    required String description,
  })? debugCreateOffice;

  @visibleForTesting
  final Future<void> Function(String officeId)? debugDeleteOffice;

  @visibleForTesting
  final Future<Map<String, dynamic>> Function({
    required String fullName,
    required String email,
    required String password,
    required String officeId,
  })? debugCreateStaff;

  @visibleForTesting
  final Future<void> Function(String userId)? debugDeleteStaff;

  @override
  State<AdminOfficesPage> createState() => _AdminOfficesPageState();
}

class _AdminOfficesPageState extends State<AdminOfficesPage> {
  final List<_AdminOfficeEntry> _offices = [];
  final List<_AdminUserEntry> _officeUsers = [];
  final TextEditingController _searchCtrl = TextEditingController();
  _TicketStats? _stats;
  bool _loading = false;
  String? _error;
  bool _requestedInitialLoad = false;
  int _page = 1;

  bool get _usesDebugSeed =>
      widget.debugOffices != null ||
      widget.debugOfficeUsers != null ||
      widget.debugStats != null;

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
    final offices = (widget.debugOffices ?? const [])
        .map(_AdminOfficeEntry.fromJson)
        .toList()
      ..sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
    final users = (widget.debugOfficeUsers ?? const [])
        .map(_AdminUserEntry.fromJson)
        .toList();
    _offices
      ..clear()
      ..addAll(offices);
    _officeUsers
      ..clear()
      ..addAll(users);
    _stats = widget.debugStats == null
        ? null
        : _TicketStats.fromJson(widget.debugStats!);
    _error = null;
    _loading = false;
    _page = _safePageFor(_filteredOffices.length);
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
      final offices = await _loadAdminOffices(context);
      final users = await _loadAdminUsers(context, role: 'office');
      _TicketStats? stats;
      try {
        stats = await _loadTicketStats(context);
      } catch (_) {
        stats = null;
      }
      if (!mounted) return;
      offices.sort(
        (a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()),
      );
      setState(() {
        _offices
          ..clear()
          ..addAll(offices);
        _officeUsers
          ..clear()
          ..addAll(users);
        _stats = stats;
        _page = _safePageFor(_filteredOffices.length);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createOffice() async {
    final created = await showDialog<_AdminOfficeEntry>(
      context: context,
      useRootNavigator: true,
      builder: (_) => _CreateOfficeDialog(
        onCreate: widget.debugCreateOffice == null
            ? null
            : ({
                required name,
                required serviceCategory,
                required description,
              }) async {
                final data = await widget.debugCreateOffice!(
                  name: name,
                  serviceCategory: serviceCategory,
                  description: description,
                );
                return _AdminOfficeEntry.fromJson(data);
              },
      ),
    );
    if (created == null) return;
    if (_usesDebugSeed) {
      setState(() {
        _offices
          ..removeWhere((office) => office.id == created.id)
          ..add(created);
        _offices.sort(
          (a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()),
        );
        _page = _safePageFor(_filteredOffices.length);
      });
    } else {
      await _load();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Office created: ${created.name}')),
    );
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

  Future<void> _createOfficeAccount(_AdminOfficeEntry office) async {
    final created = await showDialog<_AdminUserEntry>(
      context: context,
      useRootNavigator: true,
      builder: (_) => _CreateOfficeAccountDialog(
        offices: List.of(_offices),
        initialOfficeId: office.id,
        onCreate: widget.debugCreateStaff == null
            ? null
            : ({
                required fullName,
                required email,
                required password,
                required officeId,
              }) async {
                final data = await widget.debugCreateStaff!(
                  fullName: fullName,
                  email: email,
                  password: password,
                  officeId: officeId,
                );
                return _AdminUserEntry.fromJson(data);
              },
      ),
    );
    if (created == null) return;
    if (_usesDebugSeed) {
      setState(() {
        _officeUsers
          ..removeWhere((user) => user.id == created.id)
          ..add(created);
      });
    } else {
      await _load();
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Office account created for ${created.email}')),
    );
  }

  Future<void> _deleteOffice(_AdminOfficeEntry office) async {
    final confirmed = await _confirmAction(
      title: 'Delete office?',
      message:
          'Delete ${office.name}? Remove all staff accounts and reassign tickets first. This action cannot be undone.',
      confirmLabel: 'Delete',
      confirmColor: const Color(0xFFB91C1C),
    );
    if (!confirmed) return;
    try {
      if (widget.debugDeleteOffice != null) {
        await widget.debugDeleteOffice!(office.id);
      } else {
        await _deleteOfficeRequest(context, officeId: office.id);
      }
      if (_usesDebugSeed) {
        setState(() {
          _offices.removeWhere((item) => item.id == office.id);
          _officeUsers.removeWhere((user) => user.officeId == office.id);
          _page = _safePageFor(_filteredOffices.length);
        });
      } else {
        await _load();
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Office deleted: ${office.name}')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          key: const Key('admin-offices-delete-error'),
          content: Text(_friendlyError(error)),
        ),
      );
    }
  }

  Future<void> _deleteOfficeAccount(_AdminUserEntry user) async {
    final confirmed = await _confirmAction(
      title: 'Remove staff account?',
      message:
          'Delete ${user.fullName} (${user.email})? This removes the office login and the user will need to be added again later.',
      confirmLabel: 'Delete',
      confirmColor: const Color(0xFFB91C1C),
    );
    if (!confirmed) return;
    try {
      if (widget.debugDeleteStaff != null) {
        await widget.debugDeleteStaff!(user.id);
      } else {
        await _deleteOfficeAccountRequest(context, userId: user.id);
      }
      if (_usesDebugSeed) {
        setState(() {
          _officeUsers.removeWhere((item) => item.id == user.id);
        });
      } else {
        await _load();
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Staff account removed: ${user.email}')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_friendlyError(error))),
      );
    }
  }

  int _staffCount(_AdminOfficeEntry office) {
    return _officeUsers.where((user) => user.officeId == office.id).length;
  }

  int _ticketCount(_AdminOfficeEntry office) {
    final stats = _stats;
    if (stats == null) return 0;
    return stats.byOffice[office.name] ?? 0;
  }

  List<_AdminOfficeEntry> get _filteredOffices {
    final query = _searchCtrl.text.trim().toLowerCase();
    if (query.isEmpty) return _offices;
    return _offices.where((office) {
      return office.name.toLowerCase().contains(query) ||
          (office.serviceCategory ?? '').toLowerCase().contains(query);
    }).toList();
  }

  int _pageCountFor(int count) {
    if (count <= 0) return 1;
    return ((count + _kOfficePageSize - 1) / _kOfficePageSize).floor();
  }

  int _safePageFor(int count) {
    final pages = _pageCountFor(count);
    return _page.clamp(1, pages);
  }

  List<_AdminOfficeEntry> get _pageOffices {
    final filtered = _filteredOffices;
    final page = _safePageFor(filtered.length);
    final start = (page - 1) * _kOfficePageSize;
    if (start >= filtered.length) return const [];
    final end = (start + _kOfficePageSize).clamp(0, filtered.length);
    return filtered.sublist(start, end);
  }

  Future<void> _openManage(_AdminOfficeEntry office) async {
    await showGeneralDialog<void>(
      context: context,
      barrierDismissible: true,
      barrierLabel: 'Manage office',
      barrierColor: Colors.black.withValues(alpha: 0.32),
      transitionDuration: const Duration(milliseconds: 240),
      pageBuilder: (dialogContext, animation, secondaryAnimation) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            final staff = _officeUsers
                .where((user) => user.officeId == office.id)
                .toList();
            final width = MediaQuery.sizeOf(context).width;
            return Align(
              alignment: Alignment.centerRight,
              child: _ManageOfficeDrawer(
                office: office,
                staff: staff,
                ticketCount: _ticketCount(office),
                width: width < 480 ? width : 420,
                onAddStaff: () async {
                  await _createOfficeAccount(office);
                  setDialogState(() {});
                },
                onRemoveStaff: (user) async {
                  await _deleteOfficeAccount(user);
                  setDialogState(() {});
                },
                onClose: () => Navigator.of(dialogContext).pop(),
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

  @override
  Widget build(BuildContext context) {
    final filtered = _filteredOffices;
    final pageOffices = _pageOffices;
    final page = _safePageFor(filtered.length);
    final pageCount = _pageCountFor(filtered.length);
    final totalStaff = _officeUsers.length;
    final openTickets = _stats?.open ?? 0;

    return AdminScaffold(
      current: StudentNavItem.adminOffices,
      title: 'Offices',
      description:
          'Create routing offices, assign staff logins, and review ticket load.',
      fillBody: true,
      showHeader: false,
      child: ColoredBox(
        color: DesignTokens.adminSurface,
        child: LayoutBuilder(
          builder: (context, constraints) {
            final wide = constraints.maxWidth >= 900;
            return Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1180),
                child: ListView(
                  key: const Key('admin-offices-page'),
                  padding: EdgeInsets.fromLTRB(
                    wide ? 24 : 14,
                    wide ? 20 : 14,
                    wide ? 24 : 14,
                    28,
                  ),
                  children: [
                    if (_loading) const LinearProgressIndicator(minHeight: 3),
                    if (_error != null) ...[
                      _AdminNotice(
                        icon: Icons.info_outline_rounded,
                        message: _error!,
                      ),
                      const SizedBox(height: 12),
                    ],
                    _AdminOfficesHeader(
                      stacked: constraints.maxWidth < 560,
                      onAdd: _loading ? null : _createOffice,
                    ),
                    const SizedBox(height: 18),
                    _AdminOfficesStatsRow(
                      offices: _offices.length,
                      staff: totalStaff,
                      openTickets: openTickets,
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      key: const Key('admin-offices-search'),
                      controller: _searchCtrl,
                      onChanged: (_) => setState(() => _page = 1),
                      decoration: InputDecoration(
                        hintText: 'Search offices by name or category...',
                        prefixIcon: const Icon(Icons.search_rounded, size: 20),
                        suffixIcon: _searchCtrl.text.isEmpty
                            ? null
                            : IconButton(
                                onPressed: () {
                                  _searchCtrl.clear();
                                  setState(() => _page = 1);
                                },
                                icon: const Icon(Icons.clear_rounded),
                              ),
                        isDense: true,
                        filled: true,
                        fillColor: Colors.white,
                        contentPadding: const EdgeInsets.symmetric(
                          horizontal: 14,
                          vertical: 14,
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide:
                              const BorderSide(color: DesignTokens.border),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide:
                              const BorderSide(color: DesignTokens.border),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                          borderSide: const BorderSide(
                            color: DesignTokens.maroon,
                            width: 1.2,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 14),
                    if (!_loading && filtered.isEmpty)
                      _AdminOfficesEmpty(onAdd: _createOffice)
                    else
                      _AdminOfficesTable(
                        offices: pageOffices,
                        staffCountFor: _staffCount,
                        ticketCountFor: _ticketCount,
                        compact: constraints.maxWidth < 720,
                        onEdit: _openManage,
                        onDelete: _deleteOffice,
                      ),
                    if (filtered.isNotEmpty) ...[
                      const SizedBox(height: 14),
                      _AdminOfficesPager(
                        page: page,
                        pageCount: pageCount,
                        pageSize: _kOfficePageSize,
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

class _AdminOfficesHeader extends StatelessWidget {
  const _AdminOfficesHeader({
    required this.stacked,
    required this.onAdd,
  });

  final bool stacked;
  final VoidCallback? onAdd;

  @override
  Widget build(BuildContext context) {
    final copy = const Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ORGANIZATION',
          style: TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Offices',
          style: TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        SizedBox(height: 6),
        Text(
          'Create routing offices, assign staff logins, and review ticket load.',
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
      key: const Key('admin-offices-add'),
      onPressed: onAdd,
      style: ElevatedButton.styleFrom(
        backgroundColor: DesignTokens.maroon,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      child: const Text(
        'Add Office',
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
        Expanded(child: copy),
        const SizedBox(width: 12),
        add,
      ],
    );
  }
}

class _AdminOfficesStatsRow extends StatelessWidget {
  const _AdminOfficesStatsRow({
    required this.offices,
    required this.staff,
    required this.openTickets,
  });

  final int offices;
  final int staff;
  final int openTickets;

  @override
  Widget build(BuildContext context) {
    final stats = [
      (label: 'Total Offices', value: '$offices', key: 'admin-offices-stat-total'),
      (label: 'Staff Logins', value: '$staff', key: 'admin-offices-stat-staff'),
      (
        label: 'Open Tickets',
        value: '$openTickets',
        key: 'admin-offices-stat-open'
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        final columns = width >= 900
            ? 3
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
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: DesignTokens.border),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        stat.label,
                        style: const TextStyle(
                          color: DesignTokens.muted,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        stat.value,
                        style: const TextStyle(
                          color: DesignTokens.ink,
                          fontSize: 28,
                          fontWeight: FontWeight.w800,
                          height: 1,
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

class _AdminOfficesEmpty extends StatelessWidget {
  const _AdminOfficesEmpty({required this.onAdd});

  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
      ),
      child: Column(
        children: [
          const Text(
            'No offices found',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Add a new campus office or clear the search filter.',
            textAlign: TextAlign.center,
            style: TextStyle(color: DesignTokens.muted),
          ),
          const SizedBox(height: 14),
          ElevatedButton(
            onPressed: onAdd,
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.maroon,
              foregroundColor: Colors.white,
            ),
            child: const Text('Add Office'),
          ),
        ],
      ),
    );
  }
}

class _AdminOfficesTable extends StatelessWidget {
  const _AdminOfficesTable({
    required this.offices,
    required this.staffCountFor,
    required this.ticketCountFor,
    required this.compact,
    required this.onEdit,
    required this.onDelete,
  });

  final List<_AdminOfficeEntry> offices;
  final int Function(_AdminOfficeEntry office) staffCountFor;
  final int Function(_AdminOfficeEntry office) ticketCountFor;
  final bool compact;
  final ValueChanged<_AdminOfficeEntry> onEdit;
  final ValueChanged<_AdminOfficeEntry> onDelete;

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
          if (!compact) const _AdminOfficesTableHeader(),
          for (var i = 0; i < offices.length; i++) ...[
            if (i > 0 || !compact)
              const Divider(height: 1, color: DesignTokens.border),
            compact
                ? _AdminOfficesCardRow(
                    office: offices[i],
                    staffCount: staffCountFor(offices[i]),
                    ticketCount: ticketCountFor(offices[i]),
                    onEdit: () => onEdit(offices[i]),
                    onDelete: () => onDelete(offices[i]),
                  )
                : _AdminOfficesTableRow(
                    office: offices[i],
                    staffCount: staffCountFor(offices[i]),
                    ticketCount: ticketCountFor(offices[i]),
                    onEdit: () => onEdit(offices[i]),
                    onDelete: () => onDelete(offices[i]),
                  ),
          ],
        ],
      ),
    );
  }
}

class _AdminOfficesTableHeader extends StatelessWidget {
  const _AdminOfficesTableHeader();

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
          Expanded(flex: 4, child: Text('OFFICE NAME', style: style)),
          Expanded(flex: 3, child: Text('CATEGORY', style: style)),
          Expanded(flex: 2, child: Text('STAFF LOGINS', style: style)),
          Expanded(flex: 2, child: Text('OPEN TICKETS', style: style)),
          SizedBox(
            width: 120,
            child: Text('ACTIONS', style: style, textAlign: TextAlign.right),
          ),
        ],
      ),
    );
  }
}

class _AdminOfficesTableRow extends StatelessWidget {
  const _AdminOfficesTableRow({
    required this.office,
    required this.staffCount,
    required this.ticketCount,
    required this.onEdit,
    required this.onDelete,
  });

  final _AdminOfficeEntry office;
  final int staffCount;
  final int ticketCount;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final category = (office.serviceCategory ?? '').trim();
    return Padding(
      key: Key('admin-offices-row-${office.id}'),
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      child: Row(
        children: [
          Expanded(
            flex: 4,
            child: Text(
              office.name,
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
              category.isEmpty ? '—' : category,
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
              '$staffCount',
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              '$ticketCount',
              style: const TextStyle(
                color: DesignTokens.ink,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          SizedBox(
            width: 120,
            child: Wrap(
              spacing: 2,
              alignment: WrapAlignment.end,
              children: [
                _OfficeActionLink(
                  key: Key('admin-offices-edit-${office.id}'),
                  label: 'Edit',
                  color: DesignTokens.ink,
                  onTap: onEdit,
                ),
                _OfficeActionLink(
                  key: Key('admin-offices-delete-${office.id}'),
                  label: 'Delete',
                  color: const Color(0xFFB91C1C),
                  onTap: onDelete,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _AdminOfficesCardRow extends StatelessWidget {
  const _AdminOfficesCardRow({
    required this.office,
    required this.staffCount,
    required this.ticketCount,
    required this.onEdit,
    required this.onDelete,
  });

  final _AdminOfficeEntry office;
  final int staffCount;
  final int ticketCount;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final category = (office.serviceCategory ?? '').trim();
    return Padding(
      key: Key('admin-offices-row-${office.id}'),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            office.name,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 14,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            [
              if (category.isNotEmpty) category,
              '$staffCount staff login${staffCount == 1 ? '' : 's'}',
              '$ticketCount open ticket${ticketCount == 1 ? '' : 's'}',
            ].join(' · '),
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              _OfficeActionLink(
                key: Key('admin-offices-edit-${office.id}'),
                label: 'Edit',
                color: DesignTokens.ink,
                onTap: onEdit,
              ),
              const SizedBox(width: 12),
              _OfficeActionLink(
                key: Key('admin-offices-delete-${office.id}'),
                label: 'Delete',
                color: const Color(0xFFB91C1C),
                onTap: onDelete,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _OfficeActionLink extends StatelessWidget {
  const _OfficeActionLink({
    super.key,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(6),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
        child: Text(
          label,
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w800,
            fontSize: 13,
          ),
        ),
      ),
    );
  }
}

class _AdminOfficesPager extends StatelessWidget {
  const _AdminOfficesPager({
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
    final pages = _visiblePages(page, pageCount);
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 720;
        return Wrap(
          key: const Key('admin-offices-pager'),
          spacing: 4,
          runSpacing: 8,
          crossAxisAlignment: WrapCrossAlignment.center,
          alignment: compact ? WrapAlignment.start : WrapAlignment.spaceBetween,
          children: [
            Text(
              'Showing $start to $end of $filteredCount offices',
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
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
                  child: const Text('Previous'),
                ),
                for (final item in pages)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 2),
                    child: Material(
                      color: item == page ? DesignTokens.maroon : Colors.white,
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
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
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

  List<int> _visiblePages(int current, int total) {
    if (total <= 7) return [for (var i = 1; i <= total; i++) i];
    final start = (current - 3).clamp(1, total - 6);
    return [for (var i = start; i < start + 7; i++) i];
  }
}

class _ManageOfficeDrawer extends StatelessWidget {
  const _ManageOfficeDrawer({
    required this.office,
    required this.staff,
    required this.ticketCount,
    required this.onAddStaff,
    required this.onRemoveStaff,
    required this.onClose,
    this.width = 420,
  });

  final _AdminOfficeEntry office;
  final List<_AdminUserEntry> staff;
  final int ticketCount;
  final Future<void> Function() onAddStaff;
  final Future<void> Function(_AdminUserEntry user) onRemoveStaff;
  final VoidCallback onClose;
  final double width;

  @override
  Widget build(BuildContext context) {
    final category = (office.serviceCategory ?? '').trim();
    return Material(
      key: const Key('admin-offices-manage-drawer'),
      color: Colors.white,
      child: SizedBox(
        width: width,
        height: double.infinity,
        child: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Manage Office',
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                          color: DesignTokens.ink,
                        ),
                      ),
                    ),
                    IconButton(
                      key: const Key('admin-offices-manage-close'),
                      onPressed: onClose,
                      icon: const Icon(Icons.close_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  office.name,
                  key: const Key('admin-offices-manage-name'),
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: DesignTokens.ink,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  [
                    if (category.isNotEmpty) category,
                    '${staff.length} staff login${staff.length == 1 ? '' : 's'}',
                    '$ticketCount ticket${ticketCount == 1 ? '' : 's'}',
                  ].join(' · '),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Assigned staff',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color: DesignTokens.ink,
                        ),
                      ),
                    ),
                    TextButton(
                      key: const Key('admin-offices-add-staff'),
                      onPressed: onAddStaff,
                      child: const Text('Add staff'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: staff.isEmpty
                      ? const Text(
                          'No office staff accounts yet.',
                          style: TextStyle(color: DesignTokens.muted),
                        )
                      : ListView.separated(
                          itemCount: staff.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, index) {
                            final user = staff[index];
                            return ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(
                                user.fullName,
                                style: const TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 13,
                                ),
                              ),
                              subtitle: Text(
                                user.email,
                                style: const TextStyle(fontSize: 12),
                              ),
                              trailing: TextButton(
                                key: Key(
                                  'admin-offices-remove-staff-${user.id}',
                                ),
                                onPressed: () => onRemoveStaff(user),
                                style: TextButton.styleFrom(
                                  foregroundColor: const Color(0xFFB91C1C),
                                ),
                                child: const Text('Remove'),
                              ),
                            );
                          },
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
