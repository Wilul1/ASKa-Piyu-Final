import 'package:flutter/material.dart';

import '../auth/auth_navigation.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../models/auth_models.dart';
import '../widgets/student_ui.dart';
import 'login_page.dart';

class SignupPage extends StatefulWidget {
  final WidgetBuilder? returnTo;
  final String? message;

  const SignupPage({super.key, this.returnTo, this.message});

  @override
  State<SignupPage> createState() => _SignupPageState();
}

class _SignupPageState extends State<SignupPage> {
  final _formKey = GlobalKey<FormState>();
  final _nameCtrl = TextEditingController();
  final _emailCtrl = TextEditingController();
  final _studentIdCtrl = TextEditingController();
  final _passwordCtrl = TextEditingController();
  final _confirmCtrl = TextEditingController();
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _nameCtrl.dispose();
    _emailCtrl.dispose();
    _studentIdCtrl.dispose();
    _passwordCtrl.dispose();
    _confirmCtrl.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final user = await AuthScope.of(context).signup(SignupRequest(
        fullName: _nameCtrl.text,
        email: _emailCtrl.text,
        studentId: _studentIdCtrl.text,
        password: _passwordCtrl.text,
      ));
      if (!mounted) return;
      redirectAfterAuth(context, user.role, widget.returnTo);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = _friendlyError(error));
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  void _openLogin() {
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => LoginPage(returnTo: widget.returnTo, message: widget.message),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: DesignTokens.bgGrey,
      appBar: AppBar(title: const Text('Create Account')),
      body: StudentPage(
        maxWidth: 560,
        child: StudentPanel(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const StudentIconBox(
                  icon: Icons.person_add_alt_1_rounded,
                  color: DesignTokens.maroon,
                  size: 52,
                ),
                const SizedBox(height: 18),
                const Text(
                  'Create a student account',
                  style: TextStyle(
                    fontSize: 26,
                    fontWeight: FontWeight.w900,
                    color: DesignTokens.ink,
                  ),
                ),
                if (widget.message != null) ...[
                  const SizedBox(height: 10),
                  Text(
                    widget.message!,
                    style: const TextStyle(color: DesignTokens.muted, height: 1.4),
                  ),
                ],
                const SizedBox(height: 22),
                TextFormField(
                  controller: _nameCtrl,
                  textInputAction: TextInputAction.next,
                  validator: (value) => (value == null || value.trim().isEmpty)
                      ? 'Enter your full name.'
                      : null,
                  decoration: _authDecoration(
                    label: 'Full name',
                    icon: Icons.badge_outlined,
                  ),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _emailCtrl,
                  keyboardType: TextInputType.emailAddress,
                  textInputAction: TextInputAction.next,
                  validator: _validateEmail,
                  decoration: _authDecoration(
                    label: 'Email',
                    icon: Icons.alternate_email_rounded,
                  ),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _studentIdCtrl,
                  textInputAction: TextInputAction.next,
                  validator: (value) => (value == null || value.trim().isEmpty)
                      ? 'Enter your student ID.'
                      : null,
                  decoration: _authDecoration(
                    label: 'Student ID',
                    icon: Icons.confirmation_number_outlined,
                  ),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _passwordCtrl,
                  obscureText: true,
                  textInputAction: TextInputAction.next,
                  validator: (value) {
                    final text = value ?? '';
                    if (text.isEmpty) return 'Enter a password.';
                    if (text.length < 8) return 'Use at least 8 characters.';
                    return null;
                  },
                  decoration: _authDecoration(
                    label: 'Password',
                    icon: Icons.password_rounded,
                  ),
                ),
                const SizedBox(height: 14),
                TextFormField(
                  controller: _confirmCtrl,
                  obscureText: true,
                  onFieldSubmitted: (_) => _submit(),
                  validator: (value) => value != _passwordCtrl.text
                      ? 'Passwords do not match.'
                      : null,
                  decoration: _authDecoration(
                    label: 'Confirm password',
                    icon: Icons.verified_user_outlined,
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 14),
                  _ErrorBanner(message: _error!),
                ],
                const SizedBox(height: 22),
                ElevatedButton.icon(
                  onPressed: _loading ? null : _submit,
                  icon: _loading
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.person_add_alt_rounded),
                  label: Text(_loading ? 'Creating account...' : 'Create Account'),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: DesignTokens.maroon,
                    foregroundColor: Colors.white,
                    elevation: 0,
                    padding: const EdgeInsets.symmetric(vertical: 15),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                TextButton(
                  onPressed: _loading ? null : _openLogin,
                  child: const Text('I already have an account'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final String message;

  const _ErrorBanner({required this.message});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFFED7AA)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded, color: Color(0xFFC2410C)),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(color: Color(0xFF9A3412), height: 1.35),
            ),
          ),
        ],
      ),
    );
  }
}

InputDecoration _authDecoration({required String label, required IconData icon}) {
  return InputDecoration(
    labelText: label,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    prefixIcon: Icon(icon, size: 20),
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
      borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.4),
    ),
  );
}

String? _validateEmail(String? value) {
  final text = value?.trim() ?? '';
  if (text.isEmpty) return 'Enter your email address.';
  if (!text.contains('@') || !text.split('@').last.contains('.')) {
    return 'Enter a valid email address.';
  }
  return null;
}

String _friendlyError(Object error) {
  final text = error.toString().replaceFirst('Bad state: ', '').trim();
  return text.isEmpty ? 'Something went wrong. Please try again.' : text;
}
