part of 'admin_management_pages.dart';

/// Three-pane staff ticketing console (admin + office only). Text-only — no icons.
class _StaffTicketConsole extends StatefulWidget {
  final List<_AdminTicketEntry> tickets;
  final List<_AdminTicketEntry> filteredTickets;
  final TextEditingController searchCtrl;
  final String statusFilter;
  final ValueChanged<String> onStatusChanged;
  final String priorityFilter;
  final ValueChanged<String>? onPriorityChanged;
  final bool loading;
  final String? error;
  final Future<void> Function() onRefresh;
  final List<String> officeOptions;
  final bool allowReassignment;
  final String listTitle;
  final String replyHint;
  final Future<_AdminTicketEntry> Function(
    _AdminTicketEntry ticket,
    Map<String, dynamic> payload,
  ) onUpdate;
  final Future<_AdminTicketEntry> Function(
    _AdminTicketEntry ticket,
    String message, {
    bool isInternal,
  }) onReply;
  final ValueChanged<_AdminTicketEntry> onTicketChanged;
  final String? initialSelectedId;

  const _StaffTicketConsole({
    required this.tickets,
    required this.filteredTickets,
    required this.searchCtrl,
    required this.statusFilter,
    required this.onStatusChanged,
    this.priorityFilter = 'All',
    this.onPriorityChanged,
    required this.loading,
    required this.error,
    required this.onRefresh,
    required this.officeOptions,
    required this.allowReassignment,
    required this.listTitle,
    required this.replyHint,
    required this.onUpdate,
    required this.onReply,
    required this.onTicketChanged,
    this.initialSelectedId,
  });

  @override
  State<_StaffTicketConsole> createState() => _StaffTicketConsoleState();
}

class _StaffTicketConsoleState extends State<_StaffTicketConsole> {
  String? _selectedId;
  int _page = 0;
  static const int _pageSize = 8;

  @override
  void initState() {
    super.initState();
    _selectedId = widget.initialSelectedId;
    _syncPageToSelection();
  }

  /// Side pane widths (wide layout only). Kept within min/max so panes never vanish.
  double _listWidth = 320;
  double _detailsWidth = 300;
  static const double _minListWidth = 220;
  static const double _maxListWidth = 480;
  static const double _minDetailsWidth = 220;
  static const double _maxDetailsWidth = 440;
  static const double _minCenterWidth = 340;

  _AdminTicketEntry? get _selected {
    final id = _selectedId;
    if (id == null) return null;
    for (final ticket in widget.filteredTickets) {
      if (ticket.id == id) return ticket;
    }
    for (final ticket in widget.tickets) {
      if (ticket.id == id) return ticket;
    }
    return null;
  }

  (double list, double details) _effectiveWidths(double totalWidth) {
    var list = _listWidth.clamp(_minListWidth, _maxListWidth).toDouble();
    var details = _detailsWidth.clamp(_minDetailsWidth, _maxDetailsWidth).toDouble();
    final maxSides = (totalWidth - _minCenterWidth).clamp(0.0, totalWidth);
    if (list + details > maxSides && maxSides > 0) {
      final scale = maxSides / (list + details);
      list = (list * scale).clamp(_minListWidth, _maxListWidth).toDouble();
      details =
          (details * scale).clamp(_minDetailsWidth, _maxDetailsWidth).toDouble();
      if (list + details > maxSides) {
        details =
            (maxSides - list).clamp(_minDetailsWidth, _maxDetailsWidth).toDouble();
      }
    }
    return (list, details);
  }

  void _resizeList(double delta, double totalWidth) {
    setState(() {
      final maxList = (totalWidth - _detailsWidth - _minCenterWidth)
          .clamp(_minListWidth, _maxListWidth);
      _listWidth =
          (_listWidth + delta).clamp(_minListWidth, maxList).toDouble();
    });
  }

  void _resizeDetails(double delta, double totalWidth) {
    setState(() {
      // Dragging the left edge of details: positive delta (pointer right)
      // shrinks details; negative grows it.
      final maxDetails = (totalWidth - _listWidth - _minCenterWidth)
          .clamp(_minDetailsWidth, _maxDetailsWidth);
      _detailsWidth =
          (_detailsWidth - delta).clamp(_minDetailsWidth, maxDetails).toDouble();
    });
  }

  @override
  void didUpdateWidget(covariant _StaffTicketConsole oldWidget) {
    super.didUpdateWidget(oldWidget);
    final totalPages =
        (widget.filteredTickets.length / _pageSize).ceil().clamp(1, 9999);
    if (_page >= totalPages) _page = totalPages - 1;
    if (_selectedId != null &&
        widget.tickets.isNotEmpty &&
        !widget.filteredTickets.any((t) => t.id == _selectedId) &&
        !widget.tickets.any((t) => t.id == _selectedId)) {
      _selectedId = null;
    }
    _syncPageToSelection();
  }

  void _syncPageToSelection() {
    final id = _selectedId;
    if (id == null) return;
    final index = widget.filteredTickets.indexWhere((ticket) => ticket.id == id);
    if (index < 0) return;
    _page = index ~/ _pageSize;
  }

  void _selectTicket(_AdminTicketEntry ticket) {
    setState(() => _selectedId = ticket.id);
  }

  Map<String, int> get _statusCounts {
    final all = widget.tickets;
    return {
      'All': all.length,
      'Open': all.where((t) => t.status == 'Open').length,
      'In Progress': all.where((t) => t.status == 'In Progress').length,
      'Resolved': all.where((t) => t.status == 'Resolved').length,
    };
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 980;
        final pageTickets = _pageSlice(widget.filteredTickets, _page, _pageSize);
        final selected = _selected;
        final listPane = _StaffTicketListPane(
          title: widget.listTitle,
          searchCtrl: widget.searchCtrl,
          statusFilter: widget.statusFilter,
          onStatusChanged: (value) {
            setState(() => _page = 0);
            widget.onStatusChanged(value);
          },
          priorityFilter: widget.priorityFilter,
          onPriorityChanged: widget.onPriorityChanged == null
              ? null
              : (value) {
                  setState(() => _page = 0);
                  widget.onPriorityChanged!(value);
                },
          statusCounts: _statusCounts,
          tickets: pageTickets,
          allFilteredCount: widget.filteredTickets.length,
          selectedId: _selectedId,
          loading: widget.loading,
          hasAnyTickets: widget.tickets.isNotEmpty,
          page: _page,
          pageSize: _pageSize,
          onPageChanged: (page) => setState(() => _page = page),
          onRefresh: widget.onRefresh,
          onSelect: _selectTicket,
        );

        Widget threadFor(_AdminTicketEntry ticket, {required bool showBack}) {
          return _StaffTicketThreadPane(
            key: ValueKey('thread-${ticket.id}'),
            ticket: ticket,
            replyHint: widget.replyHint,
            officeOptions: widget.officeOptions,
            allowReassignment: widget.allowReassignment,
            onUpdate: (payload) => widget.onUpdate(ticket, payload),
            onReply: (message, {bool isInternal = false}) => widget.onReply(
              ticket,
              message,
              isInternal: isInternal,
            ),
            onTicketChanged: widget.onTicketChanged,
            onClearSelection: () => setState(() => _selectedId = null),
            showBackButton: showBack,
            embedDetails: !wide,
          );
        }

        if (!wide) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.loading) const LinearProgressIndicator(minHeight: 3),
              if (widget.error != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: _AdminNotice(message: widget.error!),
                ),
              Expanded(
                child: selected == null
                    ? listPane
                    : threadFor(selected, showBack: true),
              ),
            ],
          );
        }

        final widths = _effectiveWidths(constraints.maxWidth);
        final listWidth = widths.$1;
        final detailsWidth = widths.$2;
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (widget.loading) const LinearProgressIndicator(minHeight: 3),
            if (widget.error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: _AdminNotice(message: widget.error!),
              ),
            Expanded(
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(
                    width: listWidth,
                    child: DecoratedBox(
                      decoration: const BoxDecoration(
                        color: Colors.white,
                      ),
                      child: listPane,
                    ),
                  ),
                  _PaneResizeHandle(
                    onDrag: (delta) =>
                        _resizeList(delta, constraints.maxWidth),
                  ),
                  Expanded(
                    child: selected == null
                        ? const _StaffEmptyCenter()
                        : threadFor(selected, showBack: false),
                  ),
                  _PaneResizeHandle(
                    onDrag: (delta) =>
                        _resizeDetails(delta, constraints.maxWidth),
                  ),
                  SizedBox(
                    width: detailsWidth,
                    child: DecoratedBox(
                      decoration: const BoxDecoration(
                        color: Color(0xFFF8FAFC),
                      ),
                      child: selected == null
                          ? const SizedBox.expand()
                          : _StaffTicketDetailsPane(
                              key: ValueKey('details-${selected.id}'),
                              ticket: selected,
                              officeOptions: widget.officeOptions,
                              allowReassignment: widget.allowReassignment,
                              onUpdate: (payload) =>
                                  widget.onUpdate(selected, payload),
                              onTicketChanged: widget.onTicketChanged,
                            ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

/// Vertical drag strip between panes. Does not collapse panes — only resizes.
class _PaneResizeHandle extends StatefulWidget {
  final ValueChanged<double> onDrag;

  const _PaneResizeHandle({required this.onDrag});

  @override
  State<_PaneResizeHandle> createState() => _PaneResizeHandleState();
}

class _PaneResizeHandleState extends State<_PaneResizeHandle> {
  bool _hovering = false;
  bool _dragging = false;

  @override
  Widget build(BuildContext context) {
    final active = _hovering || _dragging;
    return MouseRegion(
      cursor: SystemMouseCursors.resizeColumn,
      onEnter: (_) => setState(() => _hovering = true),
      onExit: (_) => setState(() => _hovering = false),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onHorizontalDragStart: (_) => setState(() => _dragging = true),
        onHorizontalDragUpdate: (details) => widget.onDrag(details.delta.dx),
        onHorizontalDragEnd: (_) => setState(() => _dragging = false),
        onHorizontalDragCancel: () => setState(() => _dragging = false),
        child: SizedBox(
          width: 6,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              width: active ? 4 : 1,
              color: active
                  ? DesignTokens.maroon.withValues(alpha: 0.55)
                  : DesignTokens.border,
            ),
          ),
        ),
      ),
    );
  }
}

List<_AdminTicketEntry> _pageSlice(
  List<_AdminTicketEntry> tickets,
  int page,
  int pageSize,
) {
  if (tickets.isEmpty) return const [];
  final start = page * pageSize;
  if (start >= tickets.length) return const [];
  final end = (start + pageSize).clamp(0, tickets.length);
  return tickets.sublist(start, end);
}

class _StaffEmptyCenter extends StatelessWidget {
  const _StaffEmptyCenter();

  @override
  Widget build(BuildContext context) {
    return const ColoredBox(
      color: Color(0xFFFAFAFA),
      child: Center(
        child: Text(
          'Select a ticket to view the conversation.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
    );
  }
}

class _StaffTicketListPane extends StatelessWidget {
  final String title;
  final TextEditingController searchCtrl;
  final String statusFilter;
  final ValueChanged<String> onStatusChanged;
  final String priorityFilter;
  final ValueChanged<String>? onPriorityChanged;
  final Map<String, int> statusCounts;
  final List<_AdminTicketEntry> tickets;
  final int allFilteredCount;
  final String? selectedId;
  final bool loading;
  final bool hasAnyTickets;
  final int page;
  final int pageSize;
  final ValueChanged<int> onPageChanged;
  final Future<void> Function() onRefresh;
  final ValueChanged<_AdminTicketEntry> onSelect;

  const _StaffTicketListPane({
    required this.title,
    required this.searchCtrl,
    required this.statusFilter,
    required this.onStatusChanged,
    required this.priorityFilter,
    required this.onPriorityChanged,
    required this.statusCounts,
    required this.tickets,
    required this.allFilteredCount,
    required this.selectedId,
    required this.loading,
    required this.hasAnyTickets,
    required this.page,
    required this.pageSize,
    required this.onPageChanged,
    required this.onRefresh,
    required this.onSelect,
  });

  @override
  Widget build(BuildContext context) {
    final totalPages =
        (allFilteredCount / pageSize).ceil().clamp(1, 9999);
    final start = allFilteredCount == 0 ? 0 : page * pageSize + 1;
    final end = (page * pageSize + tickets.length).clamp(0, allFilteredCount);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 10),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w900,
                    fontSize: 18,
                  ),
                ),
              ),
              TextButton(
                onPressed: loading ? null : () => onRefresh(),
                child: Text(loading ? 'Refreshing…' : 'Refresh'),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: TextField(
            controller: searchCtrl,
            decoration: _adminInputDecoration(
              hintText: 'Search ticket ID, subject, or requester…',
            ),
          ),
        ),
        const SizedBox(height: 10),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final status in const [
                'All',
                'Open',
                'In Progress',
                'Resolved',
              ])
                _StaffFilterPill(
                  label: '$status (${statusCounts[status] ?? 0})',
                  selected: statusFilter == status,
                  onTap: () => onStatusChanged(status),
                ),
            ],
          ),
        ),
        if (onPriorityChanged != null) ...[
          const SizedBox(height: 8),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: DropdownButtonFormField<String>(
              value: priorityFilter,
              isDense: true,
              decoration: _adminInputDecoration(hintText: 'Priority'),
              items: const [
                DropdownMenuItem(value: 'All', child: Text('All priorities')),
                DropdownMenuItem(value: 'Low', child: Text('Low')),
                DropdownMenuItem(value: 'Medium', child: Text('Medium')),
                DropdownMenuItem(value: 'High', child: Text('High')),
                DropdownMenuItem(value: 'Urgent', child: Text('Urgent')),
              ],
              onChanged: (value) {
                if (value != null) onPriorityChanged!(value);
              },
            ),
          ),
        ],
        const SizedBox(height: 12),
        Expanded(
          child: tickets.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      hasAnyTickets
                          ? 'No matching tickets.'
                          : (loading
                              ? 'Loading tickets…'
                              : 'No tickets yet.'),
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        color: DesignTokens.muted,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                  itemCount: tickets.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final ticket = tickets[index];
                    return _StaffTicketListCard(
                      ticket: ticket,
                      selected: ticket.id == selectedId,
                      onTap: () => onSelect(ticket),
                    );
                  },
                ),
        ),
        Container(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 14),
          decoration: const BoxDecoration(
            border: Border(top: BorderSide(color: DesignTokens.border)),
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  allFilteredCount == 0
                      ? 'Showing 0 tickets'
                      : 'Showing $start–$end of $allFilteredCount tickets',
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              TextButton(
                onPressed: page <= 0 ? null : () => onPageChanged(page - 1),
                child: const Text('Prev'),
              ),
              Text(
                '${page + 1}/$totalPages',
                style: const TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 12,
                ),
              ),
              TextButton(
                onPressed: page >= totalPages - 1
                    ? null
                    : () => onPageChanged(page + 1),
                child: const Text('Next'),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _StaffFilterPill extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _StaffFilterPill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? DesignTokens.maroon : Colors.white,
      borderRadius: BorderRadius.circular(999),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected ? DesignTokens.maroon : DesignTokens.border,
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              color: selected ? Colors.white : DesignTokens.ink,
              fontWeight: FontWeight.w800,
              fontSize: 12,
            ),
          ),
        ),
      ),
    );
  }
}

class _StaffTicketListCard extends StatelessWidget {
  final _AdminTicketEntry ticket;
  final bool selected;
  final VoidCallback onTap;

  const _StaffTicketListCard({
    required this.ticket,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: selected ? const Color(0xFFF8E8EA) : Colors.white,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: selected ? DesignTokens.maroon : DesignTokens.border,
              width: selected ? 1.4 : 1,
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      ticket.id,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: selected
                            ? DesignTokens.maroon
                            : DesignTokens.muted,
                        fontWeight: FontWeight.w800,
                        fontSize: 11,
                      ),
                    ),
                  ),
                  Text(
                    _adminFormatDate(ticket.createdAt),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Text(
                ticket.subject,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.ink,
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                  height: 1.3,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                ticket.userName,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: DesignTokens.muted,
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Expanded(
                    child: Text(
                      ticket.category,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        color: DesignTokens.muted,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  _AdminStatusChip(status: ticket.status),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StaffTicketThreadPane extends StatefulWidget {
  final _AdminTicketEntry ticket;
  final String replyHint;
  final List<String> officeOptions;
  final bool allowReassignment;
  final Future<_AdminTicketEntry> Function(Map<String, dynamic> payload)
      onUpdate;
  final Future<_AdminTicketEntry> Function(
    String message, {
    bool isInternal,
  }) onReply;
  final ValueChanged<_AdminTicketEntry> onTicketChanged;
  final VoidCallback onClearSelection;
  final bool showBackButton;
  final bool embedDetails;

  const _StaffTicketThreadPane({
    super.key,
    required this.ticket,
    required this.replyHint,
    required this.officeOptions,
    required this.allowReassignment,
    required this.onUpdate,
    required this.onReply,
    required this.onTicketChanged,
    required this.onClearSelection,
    this.showBackButton = false,
    this.embedDetails = false,
  });

  @override
  State<_StaffTicketThreadPane> createState() => _StaffTicketThreadPaneState();
}

class _StaffTicketThreadPaneState extends State<_StaffTicketThreadPane> {
  late _AdminTicketEntry _ticket;
  final TextEditingController _replyCtrl = TextEditingController();
  final FocusNode _replyFocus = FocusNode();
  final ScrollController _scrollCtrl = ScrollController();
  String? _error;
  String? _pendingAttachmentName;
  bool _saving = false;
  bool _refreshing = false;
  bool _asInternalNote = false;
  int _centerTab = 0;
  List<Map<String, dynamic>> _auditEvents = const [];
  bool _loadingAudit = false;
  Timer? _pollTimer;

  static const _quickReplies = <String>[
    'Thank you for your message. We are reviewing your request and will update you shortly.',
    'Please upload a clear photo or PDF of the required document so we can continue.',
    'Your request has been processed. Kindly check your portal or email for confirmation.',
    'We need additional details before we can proceed. Please reply with more information.',
  ];

  @override
  void initState() {
    super.initState();
    _ticket = widget.ticket;
    _pollTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      if (mounted) _refreshTicket();
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _refreshTicket();
    });
  }

  @override
  void didUpdateWidget(covariant _StaffTicketThreadPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.ticket.id != widget.ticket.id) {
      _ticket = widget.ticket;
      _replyCtrl.clear();
      _error = null;
      _pendingAttachmentName = null;
      _asInternalNote = false;
      _centerTab = 0;
      _auditEvents = const [];
    } else if (widget.ticket.updatedAt != _ticket.updatedAt ||
        widget.ticket.messages.length != _ticket.messages.length) {
      _ticket = widget.ticket;
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _replyCtrl.dispose();
    _replyFocus.dispose();
    _scrollCtrl.dispose();
    super.dispose();
  }

  void _wrapSelection(String left, [String? right]) {
    final value = _replyCtrl.value;
    final text = value.text;
    final start = value.selection.start >= 0 ? value.selection.start : text.length;
    final end = value.selection.end >= 0 ? value.selection.end : text.length;
    final selected = start < end ? text.substring(start, end) : '';
    final close = right ?? left;
    final insertion = selected.isEmpty
        ? '$left$close'
        : '$left$selected$close';
    final newText = text.replaceRange(start, end, insertion);
    final cursor = selected.isEmpty
        ? start + left.length
        : start + insertion.length;
    _replyCtrl.value = TextEditingValue(
      text: newText,
      selection: TextSelection.collapsed(offset: cursor),
    );
    _replyFocus.requestFocus();
  }

  void _insertQuickReply(String reply) {
    final current = _replyCtrl.text.trim();
    _replyCtrl.text = current.isEmpty ? reply : '$current\n\n$reply';
    _replyCtrl.selection =
        TextSelection.collapsed(offset: _replyCtrl.text.length);
    _replyFocus.requestFocus();
  }

  Future<void> _pickAttachment({required bool imagesOnly}) async {
    if (_ticket.status == 'Closed') {
      setState(() => _error = 'Closed tickets do not accept attachments.');
      return;
    }
    try {
      final picked = await pickAppFile(
        allowedExtensions: imagesOnly
            ? const ['png', 'jpg', 'jpeg', 'gif', 'webp']
            : const ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'],
        dialogTitle: imagesOnly ? 'Attach image' : 'Attach file (PDF or image)',
      );
      if (picked == null || !mounted) return;
      if (picked.bytes.length > 10 * 1024 * 1024) {
        setState(() => _error = 'Attachment must be 10 MB or smaller.');
        return;
      }
      setState(() {
        _saving = true;
        _error = null;
        _pendingAttachmentName = picked.name;
      });
      final result = await ApiClient.multipart(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/attachments',
        headers: AuthScope.of(context).ticketHeaders(),
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
      await _refreshTicket(force: true);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Attached ${picked.name}')),
      );
    } catch (error) {
      if (mounted) setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) {
        setState(() {
          _saving = false;
          _pendingAttachmentName = null;
        });
      }
    }
  }

  Future<void> _downloadAttachment(_AdminTicketAttachment file) async {
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
        SnackBar(content: Text(_friendlyError(error))),
      );
    }
  }

  Future<void> _refreshTicket({bool force = false}) async {
    if (_refreshing || (_saving && !force)) return;
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
      final updated = _AdminTicketEntry.fromJson(data);
      final changed = updated.messages.length != _ticket.messages.length ||
          updated.attachments.length != _ticket.attachments.length ||
          updated.status != _ticket.status ||
          updated.updatedAt != _ticket.updatedAt;
      if (!changed && !force) return;
      setState(() => _ticket = updated);
      widget.onTicketChanged(updated);
    } catch (_) {
      // best-effort
    } finally {
      _refreshing = false;
    }
  }

  Future<void> _loadAudit() async {
    setState(() => _loadingAudit = true);
    try {
      final result = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${_ticket.id}/audit',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      if (!mounted) return;
      if (result.statusCode < 200 || result.statusCode >= 300) {
        setState(() {
          _auditEvents = const [];
          _loadingAudit = false;
        });
        return;
      }
      final decoded = jsonDecode(result.body);
      final items = decoded is List ? decoded : const [];
      setState(() {
        _auditEvents = items
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
        _loadingAudit = false;
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          _auditEvents = const [];
          _loadingAudit = false;
        });
      }
    }
  }

  void _selectCenterTab(int index) {
    setState(() => _centerTab = index);
    if (index == 2 && _auditEvents.isEmpty && !_loadingAudit) {
      _loadAudit();
    }
  }

  Future<void> _openAddToKb() async {
    final status = _ticket.status;
    if (status != 'Resolved' && status != 'Closed') {
      setState(() => _error =
          'Set status to Resolved or Closed first, then use Add to KB.');
      return;
    }
    final draftInBox = _replyCtrl.text.trim();
    final latestStaff = _ticket.messages.reversed
        .where((m) =>
            !m.isInternal &&
            (m.senderRole == 'office' || m.senderRole == 'admin'))
        .map((m) => m.message.trim())
        .firstWhere((m) => m.isNotEmpty, orElse: () => '');
    final answerSeed =
        draftInBox.isNotEmpty ? draftInBox : latestStaff;
    if (answerSeed.isEmpty) {
      setState(() => _error =
          'No office answer yet. Reply with the approved answer first, or type it below, then Add to KB.');
      return;
    }

    final updated = await Navigator.of(context).push<_AdminTicketEntry>(
      MaterialPageRoute(
        builder: (context) => _TicketKbArticleEditorPage(
          ticket: _ticket,
          initialAnswer: answerSeed,
        ),
      ),
    );
    if (!mounted || updated == null) return;
    setState(() => _ticket = updated);
    widget.onTicketChanged(updated);
  }

  Future<void> _sendReply() async {
    final message = _replyCtrl.text.trim();
    if (message.isEmpty) {
      setState(() => _error = 'Write a reply before sending.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.onReply(
        message,
        isInternal: _asInternalNote,
      );
      setState(() {
        _ticket = updated;
        _replyCtrl.clear();
        _asInternalNote = false;
      });
      widget.onTicketChanged(updated);
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _openTransferDialog() async {
    var status = _ticket.status;
    var office = _ticket.assignedOffice;
    final statuses =
        _mergeOption(const ['Open', 'In Progress', 'Resolved', 'Closed'], status);
    final offices = _mergeOption(widget.officeOptions, office);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              title: const Text('Transfer ticket'),
              content: SizedBox(
                width: 420,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    DropdownButtonFormField<String>(
                      value: statuses.contains(status) ? status : statuses.first,
                      decoration: const InputDecoration(
                        labelText: 'Status',
                        border: OutlineInputBorder(),
                      ),
                      items: statuses
                          .map((item) =>
                              DropdownMenuItem(value: item, child: Text(item)))
                          .toList(),
                      onChanged: (value) {
                        if (value == null) return;
                        setDialogState(() => status = value);
                      },
                    ),
                    if (widget.allowReassignment) ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        value: offices.contains(office) ? office : offices.first,
                        decoration: const InputDecoration(
                          labelText: 'Assigned office',
                          border: OutlineInputBorder(),
                        ),
                        items: offices
                            .map((item) => DropdownMenuItem(
                                  value: item,
                                  child: Text(item),
                                ))
                            .toList(),
                        onChanged: (value) {
                          if (value == null) return;
                          setDialogState(() => office = value);
                        },
                      ),
                    ],
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(dialogContext).pop(false),
                  child: const Text('Cancel'),
                ),
                ElevatedButton(
                  onPressed: () => Navigator.of(dialogContext).pop(true),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                  ),
                  child: const Text('Apply'),
                ),
              ],
            );
          },
        );
      },
    );
    if (confirmed != true) return;
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final updated = await widget.onUpdate({
        'status': status,
        if (widget.allowReassignment) 'assigned_office': office,
      });
      setState(() => _ticket = updated);
      widget.onTicketChanged(updated);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Ticket transfer saved.')),
      );
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: Colors.white,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (widget.showBackButton) ...[
                  TextButton(
                    onPressed: widget.onClearSelection,
                    style: TextButton.styleFrom(
                      padding: EdgeInsets.zero,
                      minimumSize: Size.zero,
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    child: const Text('Back to tickets'),
                  ),
                  const SizedBox(height: 8),
                ],
                Text(
                  _ticket.id,
                  style: const TextStyle(
                    color: DesignTokens.maroon,
                    fontWeight: FontWeight.w800,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  _ticket.subject,
                  style: const TextStyle(
                    color: DesignTokens.ink,
                    fontWeight: FontWeight.w900,
                    fontSize: 20,
                    height: 1.25,
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    _AdminStatusChip(status: _ticket.status),
                    _AdminPriorityChip(priority: _ticket.priority),
                  ],
                ),
                const SizedBox(height: 14),
                _StaffCenterTabs(
                  index: _centerTab,
                  onChanged: _selectCenterTab,
                  includeDetails: widget.embedDetails,
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(
            child: ListView(
              controller: _scrollCtrl,
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 16),
              children: [
                if (_centerTab == 0) ..._conversationTab(),
                if (_centerTab == 1 && widget.embedDetails)
                  _StaffTicketDetailsPane(
                    ticket: _ticket,
                    officeOptions: widget.officeOptions,
                    allowReassignment: widget.allowReassignment,
                    onUpdate: widget.onUpdate,
                    onTicketChanged: widget.onTicketChanged,
                    embedded: true,
                  )
                else if (_centerTab == 1)
                  ..._detailsTab()
                else if (_centerTab == 2)
                  ..._historyTab(),
              ],
            ),
          ),
          if (_centerTab == 0)
          Container(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            decoration: const BoxDecoration(
              color: Color(0xFFF8FAFC),
              border: Border(top: BorderSide(color: DesignTokens.border)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (_error != null) ...[
                  Text(
                    _error!,
                    style: const TextStyle(
                      color: Color(0xFFB91C1C),
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_pendingAttachmentName != null) ...[
                  Text(
                    'Uploading $_pendingAttachmentName…',
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
                if (_ticket.kbConversionStatus == 'draft' ||
                    _ticket.kbConversionStatus == 'published') ...[
                  Text(
                    _ticket.kbConversionStatus == 'published'
                        ? 'This ticket already has a published KB article.'
                        : 'KB draft saved — review it in Knowledge Base.',
                    style: const TextStyle(
                      color: Color(0xFF166534),
                      fontWeight: FontWeight.w700,
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                  const SizedBox(height: 8),
                ],
                TextField(
                  controller: _replyCtrl,
                  focusNode: _replyFocus,
                  minLines: 2,
                  maxLines: 5,
                  decoration: InputDecoration(
                    hintText: _asInternalNote
                        ? 'Write an internal note…'
                        : widget.replyHint,
                    filled: true,
                    fillColor: Colors.white,
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
                      borderSide: const BorderSide(
                        color: DesignTokens.maroon,
                        width: 1.4,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                _StaffReplyToolbar(
                  asInternalNote: _asInternalNote,
                  saving: _saving,
                  kbStatus: _ticket.kbConversionStatus,
                  onBold: () => _wrapSelection('**'),
                  onItalic: () => _wrapSelection('_'),
                  onUnderline: () => _wrapSelection('<u>', '</u>'),
                  onAttachImage: () => _pickAttachment(imagesOnly: true),
                  onAttachFile: () => _pickAttachment(imagesOnly: false),
                  onQuickReply: _insertQuickReply,
                  quickReplies: _quickReplies,
                  onToggleNote: () =>
                      setState(() => _asInternalNote = !_asInternalNote),
                  onTransferHint: () {
                    if (!_saving) _openTransferDialog();
                  },
                  onAddToKb: _openAddToKb,
                  onSend: _sendReply,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  List<Widget> _conversationTab() {
    final thread = <_AdminTicketMessage>[
      if (_ticket.description.trim().isNotEmpty &&
          _ticket.messages.every((m) => m.message.trim() != _ticket.description.trim()))
        _AdminTicketMessage(
          id: 'original',
          ticketId: _ticket.id,
          senderId: _ticket.userId,
          senderRole: 'student',
          senderName: _ticket.userName,
          message: _ticket.description,
          createdAt: _ticket.createdAt,
        ),
      ..._ticket.messages,
    ];
    return [
      if (thread.isEmpty)
        const Text(
          'No conversation yet.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontWeight: FontWeight.w600,
          ),
        )
      else
        ...thread.map(
          (message) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _StaffThreadBubble(message: message),
          ),
        ),
      if (_ticket.attachments.isNotEmpty) ...[
        const SizedBox(height: 8),
        const Text(
          'Attachments',
          style: TextStyle(fontWeight: FontWeight.w900, fontSize: 13),
        ),
        const SizedBox(height: 8),
        ..._ticket.attachments.map(
          (file) => Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Material(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(10),
              child: InkWell(
                onTap: () => _downloadAttachment(file),
                borderRadius: BorderRadius.circular(10),
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                  child: Text(
                    file.originalFilename,
                    style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 13),
                  ),
                ),
              ),
            ),
          ),
        ),
      ],
    ];
  }

  List<Widget> _detailsTab() {
    final profile = _ticket.requesterProfile;
    return [
      _StaffDetailRow(label: 'Requester', value: _ticket.userName),
      const SizedBox(height: 10),
      _StaffDetailRow(label: 'Email', value: _ticket.userEmail ?? '—'),
      const SizedBox(height: 10),
      _StaffDetailRow(label: 'Category', value: _ticket.category),
      const SizedBox(height: 10),
      _StaffDetailRow(label: 'Assigned office', value: _ticket.assignedOffice),
      if (profile.studentNumber != null) ...[
        const SizedBox(height: 10),
        _StaffDetailRow(label: 'Student Number', value: profile.studentNumber!),
      ],
      if (profile.campus != null) ...[
        const SizedBox(height: 10),
        _StaffDetailRow(label: 'Campus', value: profile.campus!),
      ],
      if (profile.program != null) ...[
        const SizedBox(height: 10),
        _StaffDetailRow(label: 'Program', value: profile.program!),
      ],
      if (_ticket.description.trim().isNotEmpty) ...[
        const SizedBox(height: 16),
        const Text(
          'Original request',
          style: TextStyle(fontWeight: FontWeight.w900, fontSize: 13),
        ),
        const SizedBox(height: 8),
        _AdminTextPanel(text: _ticket.description),
      ],
    ];
  }

  List<Widget> _historyTab() {
    if (_loadingAudit) {
      return const [
        Padding(
          padding: EdgeInsets.only(top: 24),
          child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      ];
    }
    if (_auditEvents.isEmpty) {
      return const [
        Text(
          'No history events yet.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontWeight: FontWeight.w600,
          ),
        ),
      ];
    }
    return [
      for (final event in _auditEvents)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: DesignTokens.border),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  (event['action'] ?? 'update').toString(),
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 13,
                  ),
                ),
                if ((event['field_name'] ?? '').toString().isNotEmpty)
                  Text(
                    '${event['field_name']}: ${event['old_value'] ?? '—'} → ${event['new_value'] ?? '—'}',
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 12,
                    ),
                  ),
                Text(
                  _adminFormatFullDate(_adminParseDate(event['created_at'])),
                  style: const TextStyle(
                    color: DesignTokens.muted,
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ),
    ];
  }
}

class _StaffCenterTabs extends StatelessWidget {
  final int index;
  final ValueChanged<int> onChanged;
  final bool includeDetails;

  const _StaffCenterTabs({
    required this.index,
    required this.onChanged,
    required this.includeDetails,
  });

  @override
  Widget build(BuildContext context) {
    final labels = includeDetails
        ? const ['Conversation', 'Details', 'History']
        : const ['Conversation', 'Details', 'History'];
    return Row(
      children: [
        for (var i = 0; i < labels.length; i++)
          Padding(
            padding: const EdgeInsets.only(right: 18),
            child: InkWell(
              onTap: () => onChanged(i),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    labels[i],
                    style: TextStyle(
                      color: index == i
                          ? DesignTokens.maroon
                          : DesignTokens.muted,
                      fontWeight: FontWeight.w800,
                      fontSize: 13,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    height: 2,
                    width: 28,
                    color: index == i
                        ? DesignTokens.maroon
                        : Colors.transparent,
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class _StaffThreadBubble extends StatelessWidget {
  final _AdminTicketMessage message;

  const _StaffThreadBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    final isStudent = message.senderRole.toLowerCase() == 'student';
    final initials = message.senderName.trim().isEmpty
        ? '?'
        : message.senderName
            .trim()
            .split(RegExp(r'\s+'))
            .take(2)
            .map((part) => part[0].toUpperCase())
            .join();
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CircleAvatar(
          radius: 16,
          backgroundColor:
              isStudent ? const Color(0xFFE2E8F0) : const Color(0xFFF3D5D8),
          child: Text(
            initials,
            style: TextStyle(
              color: isStudent ? DesignTokens.ink : DesignTokens.maroon,
              fontWeight: FontWeight.w800,
              fontSize: 11,
            ),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '${message.senderName}${isStudent ? '' : ' · Office'}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                      ),
                    ),
                  ),
                  Text(
                    _adminFormatDate(message.createdAt),
                    style: const TextStyle(
                      color: DesignTokens.muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: isStudent ? Colors.white : const Color(0xFFFBE8D8),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isStudent
                        ? DesignTokens.border
                        : const Color(0xFFF4C7A5),
                  ),
                ),
                child: Text(
                  message.message,
                  style: const TextStyle(
                    height: 1.45,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _StaffReplyToolbar extends StatelessWidget {
  final bool asInternalNote;
  final bool saving;
  final String kbStatus;
  final VoidCallback onBold;
  final VoidCallback onItalic;
  final VoidCallback onUnderline;
  final VoidCallback onAttachImage;
  final VoidCallback onAttachFile;
  final ValueChanged<String> onQuickReply;
  final List<String> quickReplies;
  final VoidCallback onToggleNote;
  final VoidCallback onTransferHint;
  final VoidCallback onAddToKb;
  final VoidCallback onSend;

  const _StaffReplyToolbar({
    required this.asInternalNote,
    required this.saving,
    required this.kbStatus,
    required this.onBold,
    required this.onItalic,
    required this.onUnderline,
    required this.onAttachImage,
    required this.onAttachFile,
    required this.onQuickReply,
    required this.quickReplies,
    required this.onToggleNote,
    required this.onTransferHint,
    required this.onAddToKb,
    required this.onSend,
  });

  @override
  Widget build(BuildContext context) {
    final iconColor = const Color(0xFF475569);
    final kbLabel = kbStatus == 'published'
        ? 'KB published'
        : kbStatus == 'draft'
            ? 'Update KB draft'
            : 'Add to KB';
    return Wrap(
      spacing: 4,
      runSpacing: 8,
      crossAxisAlignment: WrapCrossAlignment.center,
      children: [
        _ToolIconButton(
          tooltip: 'Bold',
          onPressed: saving ? null : onBold,
          child: Text(
            'B',
            style: TextStyle(
              fontWeight: FontWeight.w900,
              color: iconColor,
              fontSize: 15,
              height: 1,
            ),
          ),
        ),
        _ToolIconButton(
          tooltip: 'Italic',
          onPressed: saving ? null : onItalic,
          child: Text(
            'I',
            style: TextStyle(
              fontStyle: FontStyle.italic,
              fontWeight: FontWeight.w800,
              color: iconColor,
              fontSize: 15,
              height: 1,
              fontFamily: 'serif',
            ),
          ),
        ),
        _ToolIconButton(
          tooltip: 'Underline',
          onPressed: saving ? null : onUnderline,
          child: Text(
            'U',
            style: TextStyle(
              decoration: TextDecoration.underline,
              decorationColor: iconColor,
              fontWeight: FontWeight.w800,
              color: iconColor,
              fontSize: 15,
              height: 1,
            ),
          ),
        ),
        _ToolIconButton(
          tooltip: 'Attach image',
          onPressed: saving ? null : onAttachImage,
          child: Icon(Icons.image, size: 20, color: iconColor),
        ),
        _ToolIconButton(
          tooltip: 'Attach file (PDF or image)',
          onPressed: saving ? null : onAttachFile,
          child: Icon(Icons.attach_file, size: 20, color: iconColor),
        ),
        PopupMenuButton<String>(
          tooltip: 'Quick responses',
          enabled: !saving,
          onSelected: onQuickReply,
          itemBuilder: (context) => [
            for (final reply in quickReplies)
              PopupMenuItem(
                value: reply,
                child: SizedBox(
                  width: 320,
                  child: Text(reply, maxLines: 3),
                ),
              ),
          ],
          child: Padding(
            padding: const EdgeInsets.all(8),
            child: Icon(Icons.bolt, size: 20, color: iconColor),
          ),
        ),
        _ToolIconButton(
          tooltip: asInternalNote ? 'Internal note on' : 'Internal note',
          onPressed: saving ? null : onToggleNote,
          child: Icon(
            Icons.sticky_note_2,
            size: 20,
            color: asInternalNote ? DesignTokens.maroon : iconColor,
          ),
        ),
        _ToolIconButton(
          tooltip: 'Transfer / reassign',
          onPressed: saving ? null : onTransferHint,
          child: Icon(Icons.swap_horiz, size: 20, color: iconColor),
        ),
        const SizedBox(width: 8),
        TextButton(
          onPressed: saving ? null : onAddToKb,
          style: TextButton.styleFrom(
            foregroundColor: DesignTokens.maroon,
            padding: const EdgeInsets.symmetric(horizontal: 10),
            visualDensity: VisualDensity.compact,
          ),
          child: Text(
            kbLabel,
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
          ),
        ),
        const SizedBox(width: 8),
        FilledButton.icon(
          onPressed: saving ? null : onSend,
          style: FilledButton.styleFrom(
            backgroundColor: DesignTokens.maroon,
            foregroundColor: Colors.white,
            disabledBackgroundColor: const Color(0xFFE2E8F0),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            visualDensity: VisualDensity.compact,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
          icon: const Icon(Icons.send, size: 16),
          label: const Text(
            'Send Reply',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 12),
          ),
        ),
      ],
    );
  }
}

class _ToolIconButton extends StatelessWidget {
  final String tooltip;
  final VoidCallback? onPressed;
  final Widget child;

  const _ToolIconButton({
    required this.tooltip,
    required this.onPressed,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: child,
        ),
      ),
    );
  }
}

class _StaffTicketDetailsPane extends StatefulWidget {
  final _AdminTicketEntry ticket;
  final List<String> officeOptions;
  final bool allowReassignment;
  final Future<_AdminTicketEntry> Function(Map<String, dynamic> payload)
      onUpdate;
  final ValueChanged<_AdminTicketEntry> onTicketChanged;

  final bool embedded;

  const _StaffTicketDetailsPane({
    super.key,
    required this.ticket,
    required this.officeOptions,
    required this.allowReassignment,
    required this.onUpdate,
    required this.onTicketChanged,
    this.embedded = false,
  });

  @override
  State<_StaffTicketDetailsPane> createState() =>
      _StaffTicketDetailsPaneState();
}

class _StaffTicketDetailsPaneState extends State<_StaffTicketDetailsPane> {
  late _AdminTicketEntry _ticket;
  late String _status;
  late String _priority;
  late String _office;
  final TextEditingController _categoryCtrl = TextEditingController();
  String? _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _syncFrom(widget.ticket);
  }

  @override
  void didUpdateWidget(covariant _StaffTicketDetailsPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.ticket.id != widget.ticket.id ||
        oldWidget.ticket.updatedAt != widget.ticket.updatedAt ||
        oldWidget.ticket.status != widget.ticket.status ||
        oldWidget.ticket.priority != widget.ticket.priority) {
      _syncFrom(widget.ticket);
    }
  }

  void _syncFrom(_AdminTicketEntry ticket) {
    _ticket = ticket;
    _status = ticket.status;
    _priority = ticket.priority;
    _office = ticket.assignedOffice;
    _categoryCtrl.text = ticket.category;
    _error = null;
  }

  @override
  void dispose() {
    _categoryCtrl.dispose();
    super.dispose();
  }

  Future<void> _save({String? status, String? priority}) async {
    setState(() {
      _saving = true;
      _error = null;
      if (status != null) _status = status;
      if (priority != null) _priority = priority;
    });
    try {
      final updated = await widget.onUpdate({
        'status': status ?? _status,
        'priority': priority ?? _priority,
        if (widget.allowReassignment) 'assigned_office': _office,
        if (widget.allowReassignment) 'category': _categoryCtrl.text.trim(),
      });
      setState(() => _syncFrom(updated));
      widget.onTicketChanged(updated);
    } catch (error) {
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final statuses =
        _mergeOption(const ['Open', 'In Progress', 'Resolved', 'Closed'], _status);
    final priorities =
        _mergeOption(const ['Low', 'Medium', 'High', 'Urgent'], _priority);
    final offices = _mergeOption(widget.officeOptions, _office);

    final profile = _ticket.requesterProfile;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
      shrinkWrap: widget.embedded,
      physics: widget.embedded
          ? const NeverScrollableScrollPhysics()
          : const AlwaysScrollableScrollPhysics(),
      children: [
        const Text(
          'Ticket Details',
          style: TextStyle(
            fontWeight: FontWeight.w900,
            fontSize: 15,
            color: DesignTokens.ink,
          ),
        ),
        const SizedBox(height: 14),
        _AdminFilterDropdown(
          label: 'Status',
          value: _status,
          values: statuses,
          onChanged: (value) => _save(status: value),
        ),
        const SizedBox(height: 12),
        _AdminFilterDropdown(
          label: 'Priority',
          value: _priority,
          values: priorities,
          onChanged: (value) => _save(priority: value),
        ),
        if (widget.allowReassignment) ...[
          const SizedBox(height: 12),
          _AdminFilterDropdown(
            label: 'Assigned Office',
            value: _office,
            values: offices.isEmpty ? [_office] : offices,
            onChanged: (value) => setState(() => _office = value),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _categoryCtrl,
            decoration: _adminInputDecoration(hintText: 'Category'),
          ),
        ] else ...[
          const SizedBox(height: 16),
          _StaffDetailRow(label: 'Assigned Office', value: _ticket.assignedOffice),
          const SizedBox(height: 10),
          _StaffDetailRow(label: 'Category', value: _ticket.category),
        ],
        const SizedBox(height: 16),
        _StaffDetailRow(label: 'Requester', value: _ticket.userName),
        const SizedBox(height: 10),
        _StaffDetailRow(label: 'Email', value: _ticket.userEmail ?? '—'),
        const SizedBox(height: 10),
        _StaffDetailRow(
          label: 'Created',
          value: _adminFormatFullDate(_ticket.createdAt),
        ),
        const SizedBox(height: 10),
        _StaffDetailRow(
          label: 'Updated',
          value: _adminFormatFullDate(_ticket.updatedAt),
        ),
        const SizedBox(height: 10),
        _StaffDetailRow(
          label: 'Student Number',
          value: profile.studentNumber ?? '—',
        ),
        const SizedBox(height: 10),
        _StaffDetailRow(
          label: 'Campus',
          value: profile.campus ?? '—',
        ),
        const SizedBox(height: 10),
        _StaffDetailRow(
          label: 'Program',
          value: profile.program ?? '—',
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(
            _error!,
            style: const TextStyle(
              color: Color(0xFFB91C1C),
              fontWeight: FontWeight.w700,
              fontSize: 12,
            ),
          ),
        ],
        if (widget.allowReassignment) ...[
          const SizedBox(height: 14),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _saving ? null : _save,
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 12),
              ),
              child: Text(_saving ? 'Saving…' : 'Save changes'),
            ),
          ),
        ],
      ],
    );
  }
}

class _StaffDetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _StaffDetailRow({required this.label, required this.value});

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
        const SizedBox(height: 3),
        Text(
          value,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontSize: 13,
            fontWeight: FontWeight.w700,
            height: 1.35,
          ),
        ),
      ],
    );
  }
}

/// Full-page KB article composer for ticket → public knowledge conversion.
class _TicketKbArticleEditorPage extends StatefulWidget {
  final _AdminTicketEntry ticket;
  final String initialAnswer;

  const _TicketKbArticleEditorPage({
    required this.ticket,
    required this.initialAnswer,
  });

  @override
  State<_TicketKbArticleEditorPage> createState() =>
      _TicketKbArticleEditorPageState();
}

class _TicketKbArticleEditorPageState extends State<_TicketKbArticleEditorPage> {
  late final TextEditingController _titleCtrl;
  late final TextEditingController _categoryCtrl;
  late final TextEditingController _summaryCtrl;
  late final TextEditingController _contentCtrl;
  late final FocusNode _contentFocus;
  String _audience = 'both';
  bool _publishNow = false;
  bool _saving = false;
  bool _uploadingImage = false;
  bool _showPreview = false;
  bool _checkingDuplicate = false;
  String? _error;
  String? _duplicateWarning;
  String? _duplicateArticleTitle;
  Timer? _duplicateDebounce;
  final List<String> _attachedImageUrls = [];
  static final _markdownImageRe = RegExp(r'!\[([^\]]*)\]\(([^)]+)\)');

  @override
  void initState() {
    super.initState();
    final ticket = widget.ticket;
    _titleCtrl = TextEditingController(text: cleanFaqTitle(ticket.subject));
    _categoryCtrl = TextEditingController(
      text: ticket.category.trim().isEmpty ? 'General' : ticket.category,
    );
    _summaryCtrl = TextEditingController(
      text: shortPublicSummary(widget.initialAnswer),
    );
    _contentCtrl = TextEditingController(
      text: buildCleanPublicArticleBody(
        subject: ticket.subject,
        answer: widget.initialAnswer,
      ),
    );
    _contentCtrl.addListener(_onContentChanged);
    _titleCtrl.addListener(_onTitleChanged);
    _contentFocus = FocusNode();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _checkDuplicate();
    });
  }

  void _onContentChanged() {
    if (mounted && _showPreview) setState(() {});
  }

  void _onTitleChanged() {
    _duplicateDebounce?.cancel();
    _duplicateDebounce = Timer(const Duration(milliseconds: 450), () {
      if (mounted) _checkDuplicate();
    });
  }

  @override
  void dispose() {
    _duplicateDebounce?.cancel();
    _contentCtrl.removeListener(_onContentChanged);
    _titleCtrl.removeListener(_onTitleChanged);
    _titleCtrl.dispose();
    _categoryCtrl.dispose();
    _summaryCtrl.dispose();
    _contentCtrl.dispose();
    _contentFocus.dispose();
    super.dispose();
  }

  Future<void> _checkDuplicate() async {
    final title = _titleCtrl.text.trim();
    if (title.length < 3) {
      setState(() {
        _duplicateWarning = null;
        _duplicateArticleTitle = null;
      });
      return;
    }
    setState(() => _checkingDuplicate = true);
    try {
      final encoded = Uri.encodeQueryComponent(title);
      final result = await ApiClient.send(
        method: 'GET',
        url:
            '${AppConfig.resolvedApiBase}/tickets/${widget.ticket.id}/kb-duplicate-check?title=$encoded',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final data = _decodeObject(result.body);
      if (!mounted) return;
      if (result.statusCode < 200 || result.statusCode >= 300) {
        setState(() {
          _checkingDuplicate = false;
          _duplicateWarning = null;
          _duplicateArticleTitle = null;
        });
        return;
      }
      final hasDup = data['has_duplicate'] == true;
      setState(() {
        _checkingDuplicate = false;
        _duplicateArticleTitle =
            hasDup ? (data['title']?.toString() ?? '') : null;
        _duplicateWarning = hasDup
            ? (data['message']?.toString() ??
                'A published article already covers this topic.')
            : null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _checkingDuplicate = false;
      });
    }
  }

  void _applyCleanForPublic() {
    final cleanedTitle = cleanFaqTitle(
      _titleCtrl.text.trim().isEmpty ? widget.ticket.subject : _titleCtrl.text,
    );
    var body = _contentCtrl.text;
    if (RegExp(r'##\s*Question\b', caseSensitive: false).hasMatch(body)) {
      body = body.replaceFirstMapped(
        RegExp(
          r'(##\s*Question\s*\n+)([\s\S]*?)(?=\n##\s|\z)',
          caseSensitive: false,
        ),
        (match) => '${match.group(1)}$cleanedTitle\n',
      );
    }
    if (RegExp(r'##\s*Answer\b', caseSensitive: false).hasMatch(body)) {
      body = body.replaceFirstMapped(
        RegExp(
          r'(##\s*Answer\s*\n+)([\s\S]*?)(?=\n##\s|\z)',
          caseSensitive: false,
        ),
        (match) {
          final cleaned = cleanAnswerForPublic(match.group(2) ?? '');
          return '${match.group(1)}${cleaned.isEmpty ? (match.group(2) ?? '').trim() : cleaned}\n';
        },
      );
    } else {
      body = cleanAnswerForPublic(body);
      if (body.isEmpty) body = _contentCtrl.text;
    }
    final answerForSummary =
        _extractAnswerFromBody(body) ?? widget.initialAnswer;
    setState(() {
      _titleCtrl.text = cleanedTitle;
      _summaryCtrl.text = shortPublicSummary(answerForSummary);
      _contentCtrl.text = body.trim();
      _error = null;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'Cleaned for public: greetings and personal details removed.',
        ),
      ),
    );
    _checkDuplicate();
  }

  String? _extractAnswerFromBody(String body) {
    final match = RegExp(
      r'##\s*Answer\s*\n+([\s\S]*?)(?=\n##\s|\z)',
      caseSensitive: false,
    ).firstMatch(body);
    final answer = match?.group(1)?.trim();
    if (answer != null && answer.isNotEmpty) return answer;
    // If body has no Answer heading, treat whole non-question text as answer.
    final withoutQuestion = body.replaceFirst(
      RegExp(r'##\s*Question\s*\n+[\s\S]*?(?=\n##\s|\z)', caseSensitive: false),
      '',
    );
    final leftover = withoutQuestion.trim();
    return leftover.isEmpty ? null : leftover;
  }

  void _insertTemplateSection(String heading, String hint) {
    final next = insertFaqSection(_contentCtrl.text, heading, hint);
    if (next == _contentCtrl.text) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$heading is already in the article.')),
      );
      return;
    }
    setState(() {
      _contentCtrl.text = next;
      _showPreview = false;
    });
    _contentFocus.requestFocus();
  }

  List<(String alt, String url)> _imagesInBody() {
    return _markdownImageRe
        .allMatches(_contentCtrl.text)
        .map((match) => (match.group(1) ?? '', match.group(2) ?? ''))
        .where((entry) => entry.$2.trim().isNotEmpty)
        .toList();
  }

  String _absoluteMediaUrl(String raw) {
    final url = raw.trim();
    if (url.startsWith('http://') || url.startsWith('https://')) return url;
    return '${AppConfig.resolvedApiBase}$url';
  }

  void _removeAttachedImage(String url) {
    var text = _contentCtrl.text.replaceAll(
      RegExp(r'!\[([^\]]*)\]\(' + RegExp.escape(url) + r'\)'),
      '',
    );
    text = text.replaceAll(RegExp(r'\n{3,}'), '\n\n').trimRight();
    _contentCtrl.value = TextEditingValue(
      text: text,
      selection: TextSelection.collapsed(offset: text.length),
    );
    setState(() => _attachedImageUrls.remove(url));
  }

  void _wrapSelection(String left, [String? right]) {
    final value = _contentCtrl.value;
    final text = value.text;
    final start = value.selection.start >= 0 ? value.selection.start : text.length;
    final end = value.selection.end >= 0 ? value.selection.end : text.length;
    final selected = start < end ? text.substring(start, end) : '';
    final close = right ?? left;
    final insertion =
        selected.isEmpty ? '$left$close' : '$left$selected$close';
    final newText = text.replaceRange(start, end, insertion);
    final cursor =
        selected.isEmpty ? start + left.length : start + insertion.length;
    _contentCtrl.value = TextEditingValue(
      text: newText,
      selection: TextSelection.collapsed(offset: cursor),
    );
    _contentFocus.requestFocus();
  }

  Future<void> _insertImage() async {
    if (_uploadingImage || _saving) return;
    try {
      final picked = await pickAppFile(
        allowedExtensions: const ['png', 'jpg', 'jpeg', 'gif', 'webp'],
        dialogTitle: 'Attach image to article',
      );
      if (picked == null || !mounted) return;
      if (picked.bytes.length > 5 * 1024 * 1024) {
        setState(() => _error = 'Image must be 5 MB or smaller.');
        return;
      }
      setState(() {
        _uploadingImage = true;
        _error = null;
      });
      final headers = AuthScope.of(context).ticketHeaders();
      final result = await ApiClient.multipart(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/${widget.ticket.id}/kb-images',
        headers: headers,
        files: [
          http.MultipartFile.fromBytes(
            'file',
            picked.bytes,
            filename: picked.name,
          ),
        ],
      );
      final data = _decodeObject(result.body);
      if (result.statusCode < 200 || result.statusCode >= 300) {
        throw StateError(_extractError(data, 'Image upload failed.'));
      }
      final relativeUrl = (data['url'] ?? '').toString();
      if (relativeUrl.isEmpty) {
        throw StateError('Upload succeeded but no image URL was returned.');
      }
      final absUrl = relativeUrl.startsWith('http')
          ? relativeUrl
          : '${AppConfig.resolvedApiBase}$relativeUrl';
      final markdown = '\n\n![${picked.name}]($absUrl)\n\n';
      final text = _contentCtrl.text;
      final cursor = _contentCtrl.selection.start >= 0
          ? _contentCtrl.selection.start
          : text.length;
      final next = text.replaceRange(cursor, cursor, markdown);
      _contentCtrl.value = TextEditingValue(
        text: next,
        selection: TextSelection.collapsed(offset: cursor + markdown.length),
      );
      setState(() {
        _attachedImageUrls.add(absUrl);
        _showPreview = true;
      });
    } catch (error) {
      if (mounted) setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _uploadingImage = false);
    }
  }

  Future<void> _save({required bool publish}) async {
    final title = _titleCtrl.text.trim();
    final content = _contentCtrl.text.trim();
    final category = _categoryCtrl.text.trim();
    final summary = _summaryCtrl.text.trim();
    if (title.length < 3) {
      setState(() => _error = 'Enter a clear article title.');
      return;
    }
    if (content.length < 40) {
      setState(() => _error = 'Write a fuller article body before saving.');
      return;
    }
    if (category.length < 2) {
      setState(() => _error = 'Enter a category for the public Knowledge Base.');
      return;
    }
    await _checkDuplicate();
    if (!mounted) return;
    if (_duplicateWarning != null) {
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Possible duplicate article'),
          content: Text(
            _duplicateWarning!,
            style: const TextStyle(height: 1.4),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(),
              child: const Text('Edit title'),
            ),
          ],
        ),
      );
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
      _publishNow = publish;
    });
    try {
      final body = <String, dynamic>{
        'title': title,
        'content': content,
        'category': category,
        'summary': summary.isEmpty ? null : summary,
        'audience': _audience,
        'publish': publish,
      };
      final result = await ApiClient.send(
        method: 'POST',
        url:
            '${AppConfig.resolvedApiBase}/tickets/${widget.ticket.id}/convert-to-article',
        headers: {...AuthScope.of(context).ticketHeaders()},
        jsonBody: body,
      );
      final data = _decodeObject(result.body);
      if (result.statusCode < 200 || result.statusCode >= 300) {
        throw StateError(_extractError(data, 'Could not save KB article.'));
      }
      final refresh = await ApiClient.send(
        method: 'GET',
        url: '${AppConfig.resolvedApiBase}/tickets/${widget.ticket.id}',
        headers: AuthScope.of(context).ticketHeaders(),
      );
      final refreshed = _decodeObject(refresh.body);
      if (!mounted) return;
      if (refresh.statusCode >= 200 && refresh.statusCode < 300) {
        final updated = _AdminTicketEntry.fromJson(refreshed);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              publish
                  ? 'Article published to the public Knowledge Base.'
                  : 'KB draft saved. Open Knowledge Base to review and publish.',
            ),
            duration: const Duration(seconds: 5),
          ),
        );
        Navigator.of(context).pop(updated);
        return;
      }
      Navigator.of(context).pop();
    } catch (error) {
      if (mounted) setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  InputDecoration _fieldDecoration(String label, {String? hint}) {
    return InputDecoration(
      labelText: label,
      hintText: hint,
      filled: true,
      fillColor: Colors.white,
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
        borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.4),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final busy = _saving || _uploadingImage;
    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FB),
      appBar: AppBar(
        backgroundColor: Colors.white,
        foregroundColor: DesignTokens.ink,
        elevation: 0,
        titleSpacing: 0,
        title: const Text(
          'Compose KB article',
          style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18),
        ),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(1),
          child: Container(height: 1, color: DesignTokens.border),
        ),
        actions: [
          TextButton(
            onPressed: busy ? null : () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          const SizedBox(width: 4),
          TextButton(
            onPressed: busy ? null : () => _save(publish: false),
            child: Text(_saving && !_publishNow ? 'Saving…' : 'Save draft'),
          ),
          const SizedBox(width: 4),
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: ElevatedButton(
              onPressed: busy ? null : () => _save(publish: true),
              style: ElevatedButton.styleFrom(
                backgroundColor: DesignTokens.maroon,
                foregroundColor: Colors.white,
                elevation: 0,
              ),
              child: Text(_saving && _publishNow ? 'Publishing…' : 'Publish'),
            ),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 920),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 40),
            children: [
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
                  children: [
                    Text(
                      widget.ticket.id,
                      style: const TextStyle(
                        color: DesignTokens.maroon,
                        fontWeight: FontWeight.w800,
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'From ticket · ${widget.ticket.assignedOffice}',
                      style: const TextStyle(
                        color: DesignTokens.muted,
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Edit this into a clear public FAQ. Students will see the published version in Knowledge Base.',
                      style: TextStyle(
                        color: DesignTokens.ink,
                        height: 1.4,
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              if (_error != null) ...[
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFEF2F2),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFFECACA)),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(
                      color: Color(0xFFB91C1C),
                      fontWeight: FontWeight.w700,
                      fontSize: 13,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
              ],
              if (_duplicateWarning != null) ...[
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFFBEB),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: const Color(0xFFFDE68A)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Duplicate warning',
                        style: TextStyle(
                          color: Color(0xFF92400E),
                          fontWeight: FontWeight.w900,
                          fontSize: 13,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        _duplicateWarning!,
                        style: const TextStyle(
                          color: Color(0xFF92400E),
                          fontWeight: FontWeight.w600,
                          fontSize: 13,
                          height: 1.4,
                        ),
                      ),
                      if ((_duplicateArticleTitle ?? '').isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Text(
                          'Existing: $_duplicateArticleTitle',
                          style: const TextStyle(
                            color: Color(0xFF78350F),
                            fontWeight: FontWeight.w800,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 16),
              ] else if (_checkingDuplicate) ...[
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Text(
                    'Checking for similar published articles…',
                    style: TextStyle(
                      color: DesignTokens.muted,
                      fontWeight: FontWeight.w600,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: busy ? null : _applyCleanForPublic,
                  icon: const Icon(Icons.cleaning_services_outlined, size: 18),
                  label: const Text('Clean for public'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: DesignTokens.maroon,
                    side: const BorderSide(color: DesignTokens.maroon),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _titleCtrl,
                enabled: !busy,
                decoration: _fieldDecoration('Article title'),
              ),
              const SizedBox(height: 12),
              LayoutBuilder(
                builder: (context, constraints) {
                  final wide = constraints.maxWidth >= 640;
                  final category = TextField(
                    controller: _categoryCtrl,
                    enabled: !busy,
                    decoration: _fieldDecoration('Category'),
                  );
                  final audience = DropdownButtonFormField<String>(
                    value: _audience,
                    decoration: _fieldDecoration('Audience'),
                    items: const [
                      DropdownMenuItem(value: 'student', child: Text('Student')),
                      DropdownMenuItem(value: 'faculty', child: Text('Faculty')),
                      DropdownMenuItem(value: 'both', child: Text('Both')),
                    ],
                    onChanged: busy
                        ? null
                        : (value) {
                            if (value == null) return;
                            setState(() => _audience = value);
                          },
                  );
                  if (!wide) {
                    return Column(
                      children: [
                        category,
                        const SizedBox(height: 12),
                        audience,
                      ],
                    );
                  }
                  return Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: category),
                      const SizedBox(width: 12),
                      Expanded(child: audience),
                    ],
                  );
                },
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _summaryCtrl,
                enabled: !busy,
                minLines: 2,
                maxLines: 3,
                decoration: _fieldDecoration(
                  'Short summary',
                  hint: 'One or two sentences shown in article lists',
                ),
              ),
              const SizedBox(height: 12),
              const Text(
                'FAQ sections',
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Add structured headings students expect in a service FAQ.',
                style: TextStyle(
                  color: DesignTokens.muted,
                  fontWeight: FontWeight.w600,
                  fontSize: 12,
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final section in faqTemplateSections)
                    ActionChip(
                      label: Text(section.label),
                      onPressed: busy
                          ? null
                          : () => _insertTemplateSection(
                                section.heading,
                                section.hint,
                              ),
                    ),
                ],
              ),
              const SizedBox(height: 16),
              Container(
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: DesignTokens.border),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(12, 10, 12, 0),
                      child: Row(
                        children: [
                          const Expanded(
                            child: Text(
                              'Article body',
                              style: TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 13,
                              ),
                            ),
                          ),
                          _WritePreviewToggle(
                            preview: _showPreview,
                            onChanged: (value) =>
                                setState(() => _showPreview = value),
                          ),
                          if (!_showPreview) ...[
                            _ToolIconButton(
                              tooltip: 'Bold',
                              onPressed:
                                  busy ? null : () => _wrapSelection('**'),
                              child: const Text('B',
                                  style: TextStyle(fontWeight: FontWeight.w900)),
                            ),
                            _ToolIconButton(
                              tooltip: 'Italic',
                              onPressed:
                                  busy ? null : () => _wrapSelection('_'),
                              child: const Text('I',
                                  style: TextStyle(fontStyle: FontStyle.italic)),
                            ),
                          ],
                          _ToolIconButton(
                            tooltip: 'Attach image',
                            onPressed: busy ? null : _insertImage,
                            child: Icon(
                              Icons.image,
                              size: 20,
                              color: _uploadingImage
                                  ? DesignTokens.muted
                                  : const Color(0xFF475569),
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (_uploadingImage)
                      const Padding(
                        padding: EdgeInsets.fromLTRB(14, 4, 14, 0),
                        child: Text(
                          'Uploading image…',
                          style: TextStyle(
                            color: DesignTokens.muted,
                            fontWeight: FontWeight.w700,
                            fontSize: 12,
                          ),
                        ),
                      ),
                    if (_showPreview)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(14, 10, 14, 16),
                        child: ConstrainedBox(
                          constraints: const BoxConstraints(minHeight: 280),
                          child: _KbComposePreview(
                            content: _contentCtrl.text,
                            resolveUrl: _absoluteMediaUrl,
                          ),
                        ),
                      )
                    else
                      TextField(
                        controller: _contentCtrl,
                        focusNode: _contentFocus,
                        enabled: !busy,
                        minLines: 14,
                        maxLines: 24,
                        decoration: const InputDecoration(
                          hintText:
                              'Write the public FAQ. Use ## headings and attach images as needed.',
                          border: InputBorder.none,
                          contentPadding: EdgeInsets.fromLTRB(14, 10, 14, 16),
                        ),
                      ),
                    if (!_showPreview && _imagesInBody().isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Attached images',
                              style: TextStyle(
                                fontWeight: FontWeight.w800,
                                fontSize: 12,
                                color: DesignTokens.muted,
                              ),
                            ),
                            const SizedBox(height: 8),
                            Wrap(
                              spacing: 10,
                              runSpacing: 10,
                              children: _imagesInBody()
                                  .map(
                                    (image) => _KbComposeImageThumb(
                                      alt: image.$1,
                                      url: _absoluteMediaUrl(image.$2),
                                      onRemove: busy
                                          ? null
                                          : () =>
                                              _removeAttachedImage(image.$2),
                                    ),
                                  )
                                  .toList(),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              Row(
                children: [
                  OutlinedButton(
                    onPressed: busy ? null : () => _save(publish: false),
                    child: const Text('Save as draft'),
                  ),
                  const SizedBox(width: 10),
                  ElevatedButton(
                    onPressed: busy ? null : () => _save(publish: true),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: DesignTokens.maroon,
                      foregroundColor: Colors.white,
                      elevation: 0,
                    ),
                    child: const Text('Publish to public KB'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _WritePreviewToggle extends StatelessWidget {
  final bool preview;
  final ValueChanged<bool> onChanged;

  const _WritePreviewToggle({
    required this.preview,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(right: 6),
      decoration: BoxDecoration(
        color: const Color(0xFFF1F5F9),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          _chip('Write', !preview, () => onChanged(false)),
          _chip('Preview', preview, () => onChanged(true)),
        ],
      ),
    );
  }

  Widget _chip(String label, bool selected, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? Colors.white : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: selected ? DesignTokens.border : Colors.transparent,
          ),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w800,
            color: selected ? DesignTokens.maroon : DesignTokens.muted,
          ),
        ),
      ),
    );
  }
}

class _KbComposePreview extends StatelessWidget {
  final String content;
  final String Function(String url) resolveUrl;

  const _KbComposePreview({
    required this.content,
    required this.resolveUrl,
  });

  static final _headingRe = RegExp(r'^(#{1,3})\s+(.+)$');
  static final _imageOnlyRe = RegExp(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$');

  @override
  Widget build(BuildContext context) {
    final lines = content.replaceAll('\r\n', '\n').split('\n');
    final children = <Widget>[
      const Padding(
        padding: EdgeInsets.only(bottom: 12),
        child: Text(
          'This is how the article will look in Knowledge Base, including images.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontWeight: FontWeight.w600,
            fontSize: 12,
          ),
        ),
      ),
    ];

    var hasBody = false;
    for (final raw in lines) {
      final line = raw.trimRight();
      if (line.trim().isEmpty) {
        children.add(const SizedBox(height: 8));
        continue;
      }
      hasBody = true;
      final image = _imageOnlyRe.firstMatch(line.trim());
      if (image != null) {
        children.add(
          _KbComposePreviewImage(
            alt: image.group(1) ?? '',
            url: resolveUrl(image.group(2) ?? ''),
          ),
        );
        continue;
      }
      final heading = _headingRe.firstMatch(line.trim());
      if (heading != null) {
        final level = heading.group(1)!.length;
        children.add(
          Padding(
            padding: const EdgeInsets.only(top: 8, bottom: 4),
            child: Text(
              heading.group(2)!,
              style: TextStyle(
                fontWeight: FontWeight.w800,
                fontSize: level == 1 ? 22 : (level == 2 ? 18 : 16),
                color: DesignTokens.ink,
              ),
            ),
          ),
        );
        continue;
      }
      children.add(
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            line,
            style: const TextStyle(
              fontSize: 14,
              height: 1.5,
              color: DesignTokens.ink,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      );
    }

    if (!hasBody) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 24),
        child: Text(
          'Nothing to preview yet. Write the article, then open Preview to check images and formatting.',
          style: TextStyle(
            color: DesignTokens.muted,
            fontWeight: FontWeight.w600,
          ),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: children,
    );
  }
}

class _KbComposePreviewImage extends StatelessWidget {
  final String alt;
  final String url;

  const _KbComposePreviewImage({
    required this.alt,
    required this.url,
  });

  @override
  Widget build(BuildContext context) {
    final captionLooksLikeFilename = RegExp(
      r'\.(png|jpe?g|gif|webp)$',
      caseSensitive: false,
    ).hasMatch(alt.trim());
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.network(
              url,
              fit: BoxFit.contain,
              loadingBuilder: (context, child, progress) {
                if (progress == null) return child;
                return Container(
                  height: 180,
                  alignment: Alignment.center,
                  color: const Color(0xFFF8FAFC),
                  child: const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              },
              errorBuilder: (_, __, ___) => Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                color: const Color(0xFFF1F5F9),
                child: Text(
                  alt.trim().isEmpty ? 'Image unavailable' : alt,
                  style: const TextStyle(color: DesignTokens.muted),
                ),
              ),
            ),
          ),
          if (alt.trim().isNotEmpty && !captionLooksLikeFilename) ...[
            const SizedBox(height: 6),
            Text(
              alt,
              style: const TextStyle(
                fontSize: 12,
                color: DesignTokens.muted,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _KbComposeImageThumb extends StatelessWidget {
  final String alt;
  final String url;
  final VoidCallback? onRemove;

  const _KbComposeImageThumb({
    required this.alt,
    required this.url,
    this.onRemove,
  });

  @override
  Widget build(BuildContext context) {
    final label = alt.trim().isEmpty ? url.split('/').last : alt;
    return SizedBox(
      width: 200,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Stack(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.network(
                  url,
                  width: 200,
                  height: 140,
                  fit: BoxFit.cover,
                  loadingBuilder: (context, child, progress) {
                    if (progress == null) return child;
                    return Container(
                      width: 200,
                      height: 140,
                      alignment: Alignment.center,
                      color: const Color(0xFFF1F5F9),
                      child: const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    );
                  },
                  errorBuilder: (_, __, ___) => Container(
                    width: 200,
                    height: 140,
                    alignment: Alignment.center,
                    color: const Color(0xFFF1F5F9),
                    child: const Icon(Icons.broken_image_outlined,
                        color: DesignTokens.muted),
                  ),
                ),
              ),
              if (onRemove != null)
                Positioned(
                  top: 6,
                  right: 6,
                  child: Material(
                    color: Colors.black54,
                    shape: const CircleBorder(),
                    child: InkWell(
                      customBorder: const CircleBorder(),
                      onTap: onRemove,
                      child: const Padding(
                        padding: EdgeInsets.all(4),
                        child: Icon(Icons.close, size: 16, color: Colors.white),
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: DesignTokens.muted,
            ),
          ),
        ],
      ),
    );
  }
}
