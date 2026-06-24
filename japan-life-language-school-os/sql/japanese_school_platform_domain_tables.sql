create table if not exists school_platform_staff (
    id uuid primary key,
    name text not null,
    role text not null,
    department text not null,
    title text not null
);

create table if not exists school_platform_users (
    id uuid primary key,
    email text not null unique,
    name text not null,
    password_hash text not null,
    role text not null,
    staff_id uuid null,
    permissions jsonb not null default '[]'::jsonb,
    status text not null,
    parent_user_id uuid null,
    account_type text not null default 'primary',
    scope_label text null,
    note text null
);

create table if not exists school_platform_courses (
    id uuid primary key,
    slug text not null unique,
    name text not null,
    course_type text not null,
    level text not null,
    delivery_mode text not null,
    price numeric(12,2) not null,
    short_description text not null,
    objectives jsonb not null default '[]'::jsonb,
    highlights jsonb not null default '[]'::jsonb,
    modules jsonb not null default '[]'::jsonb,
    teacher_names jsonb not null default '[]'::jsonb
);

create table if not exists school_platform_course_modules (
    id uuid primary key,
    course_slug text not null,
    title text not null,
    description text not null,
    sort_order integer not null,
    material_url text null,
    owner_type text not null,
    status text not null,
    created_by text not null,
    updated_by text null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_classes (
    id uuid primary key,
    course_id uuid not null,
    course_slug text not null,
    name text not null,
    teacher_name text not null,
    start_date date not null,
    end_date date not null,
    weekday text not null,
    start_time time not null,
    end_time time not null,
    capacity integer not null,
    enrolled_count integer not null,
    location_label text not null,
    status text not null
);

create table if not exists school_platform_teaching_materials (
    id uuid primary key,
    course_slug text not null,
    class_id uuid null,
    title text not null,
    description text not null,
    material_url text null,
    storage_kind text not null default 'external_url',
    file_name text null,
    stored_path text null,
    mime_type text null,
    file_size_bytes integer null,
    owner_type text not null,
    visibility text not null,
    status text not null,
    created_by text not null,
    updated_by text null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_leads (
    id uuid primary key,
    name text not null,
    phone text null,
    email text null,
    line_id text null,
    source_channel text not null,
    campaign_name text null,
    interested_course_slug text null,
    budget_range text null,
    japanese_level text null,
    study_goal text null,
    departure_plan_date date null,
    intent_score numeric(10,2) not null default 0,
    win_probability numeric(10,2) not null default 0,
    status text not null,
    assigned_staff_name text null,
    last_contact_at timestamptz null,
    next_follow_up_at timestamptz null,
    notes text null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_lead_logs (
    id uuid primary key,
    lead_id uuid not null,
    staff_name text not null,
    contact_method text not null,
    content text not null,
    next_action text null,
    created_at timestamptz not null
);

create table if not exists school_platform_students (
    id uuid primary key,
    chinese_name text not null,
    email text not null,
    phone text null,
    japanese_level text null,
    study_goal text null,
    status text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_enrollments (
    id uuid primary key,
    student_id uuid not null,
    class_id uuid not null,
    status text not null,
    payment_status text not null,
    list_price numeric(12,2) not null,
    paid_amount numeric(12,2) not null,
    created_at timestamptz not null
);

create table if not exists school_platform_payments (
    id uuid primary key,
    enrollment_id uuid not null,
    order_no text not null unique,
    amount numeric(12,2) not null,
    payment_method text not null,
    status text not null,
    provider text null,
    provider_payment_id text null,
    checkout_url text null,
    client_token text null,
    currency text null,
    provider_status text null,
    checkout_expires_at timestamptz null,
    last_reconciled_at timestamptz null,
    provider_last_error text null,
    paid_at timestamptz null,
    created_at timestamptz not null,
    updated_at timestamptz null
);

create table if not exists school_platform_job_positions (
    id uuid primary key,
    title text not null,
    department text not null,
    employment_type text not null,
    location_label text not null,
    salary_range text not null,
    summary text not null,
    requirements jsonb not null default '[]'::jsonb,
    status text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_applicants (
    id uuid primary key,
    position_id uuid not null,
    name text not null,
    email text not null,
    phone text null,
    resume_link text null,
    note text null,
    ai_match_score numeric(12,2) not null,
    interview_status text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_interviews (
    id uuid primary key,
    applicant_id uuid not null,
    interview_at timestamptz not null,
    interviewer_name text not null,
    format text not null,
    status text not null,
    feedback text null,
    created_at timestamptz not null
);

create table if not exists school_platform_onboarding_records (
    id uuid primary key,
    applicant_id uuid not null,
    owner_name text not null,
    stage text not null,
    start_date date null,
    probation_status text not null,
    probation_end_date date null,
    checklist_items jsonb not null default '[]'::jsonb,
    notes text null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_teacher_manual_sections (
    id uuid primary key,
    slug text not null unique,
    title text not null,
    summary text not null,
    content text not null,
    estimated_minutes integer not null default 0,
    required boolean not null default true,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_teacher_verification_questions (
    id uuid primary key,
    section_slug text not null,
    prompt text not null,
    options jsonb not null default '[]'::jsonb,
    correct_option text not null,
    explanation text null,
    sort_order integer not null default 0,
    created_at timestamptz not null
);

create table if not exists school_platform_teacher_verification_attempts (
    id uuid primary key,
    teacher_name text not null,
    teacher_email text null,
    score numeric(12,2) not null,
    passed boolean not null,
    required_score numeric(12,2) not null,
    question_ids jsonb not null default '[]'::jsonb,
    answers jsonb not null default '{}'::jsonb,
    weak_section_slugs jsonb not null default '[]'::jsonb,
    unlocked_permission boolean not null default false,
    submitted_at timestamptz not null,
    reviewer_note text null
);

create table if not exists school_platform_assignments (
    id uuid primary key,
    class_id uuid not null,
    title text not null,
    content text not null,
    due_at timestamptz not null,
    created_by text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_assignment_submissions (
    id uuid primary key,
    assignment_id uuid not null,
    student_id uuid not null,
    content text not null,
    status text not null,
    submitted_at timestamptz not null,
    feedback text null,
    score numeric(12,2) null
);

create table if not exists school_platform_attendance (
    id uuid primary key,
    class_id uuid not null,
    student_id uuid not null,
    class_date date not null,
    status text not null,
    note text null,
    marked_by text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_exams (
    id uuid primary key,
    class_id uuid not null,
    title text not null,
    exam_type text not null,
    instructions text not null,
    total_score numeric(12,2) not null,
    due_at timestamptz not null,
    created_by text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_exam_submissions (
    id uuid primary key,
    exam_id uuid not null,
    student_id uuid not null,
    content text not null,
    status text not null,
    submitted_at timestamptz not null,
    feedback text null,
    score numeric(12,2) null,
    graded_by text null
);

create table if not exists school_platform_teaching_session_records (
    id uuid primary key,
    class_id uuid not null,
    teacher_name text not null,
    class_date date not null,
    summary text not null,
    materials_link text null,
    homework_summary text null,
    next_class_focus text null,
    student_risk_notes jsonb not null default '[]'::jsonb,
    approval_status text not null,
    review_note text null,
    reviewed_by text null,
    submitted_at timestamptz null,
    reviewed_at timestamptz null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists school_platform_ai_logs (
    id uuid primary key,
    module_name text not null,
    actor_email text null,
    action_name text not null,
    input_summary text not null,
    output_summary text not null,
    created_at timestamptz not null
);

create table if not exists school_platform_notifications (
    id uuid primary key,
    user_email text null,
    channel text not null,
    type text not null,
    title text not null,
    content text not null,
    status text not null,
    created_at timestamptz not null,
    external_recipient text null,
    provider text null,
    provider_message_id text null,
    error_message text null,
    attempt_count integer not null default 0,
    last_attempt_at timestamptz null,
    delivered_at timestamptz null,
    updated_at timestamptz null
);

alter table if exists school_platform_users add column if not exists permissions jsonb not null default '[]'::jsonb;
alter table if exists school_platform_users add column if not exists status text not null default 'active';
alter table if exists school_platform_users add column if not exists parent_user_id uuid null;
alter table if exists school_platform_users add column if not exists account_type text not null default 'primary';
alter table if exists school_platform_users add column if not exists scope_label text null;
alter table if exists school_platform_users add column if not exists note text null;

alter table if exists school_platform_payments add column if not exists provider text null;
alter table if exists school_platform_payments add column if not exists provider_payment_id text null;
alter table if exists school_platform_payments add column if not exists checkout_url text null;
alter table if exists school_platform_payments add column if not exists client_token text null;
alter table if exists school_platform_payments add column if not exists currency text null;
alter table if exists school_platform_payments add column if not exists provider_status text null;
alter table if exists school_platform_payments add column if not exists checkout_expires_at timestamptz null;
alter table if exists school_platform_payments add column if not exists last_reconciled_at timestamptz null;
alter table if exists school_platform_payments add column if not exists provider_last_error text null;
alter table if exists school_platform_payments add column if not exists updated_at timestamptz null;

alter table if exists school_platform_notifications add column if not exists external_recipient text null;
alter table if exists school_platform_notifications add column if not exists provider text null;
alter table if exists school_platform_notifications add column if not exists provider_message_id text null;
alter table if exists school_platform_notifications add column if not exists error_message text null;
alter table if exists school_platform_notifications add column if not exists attempt_count integer not null default 0;
alter table if exists school_platform_notifications add column if not exists last_attempt_at timestamptz null;
alter table if exists school_platform_notifications add column if not exists delivered_at timestamptz null;
alter table if exists school_platform_notifications add column if not exists updated_at timestamptz null;
