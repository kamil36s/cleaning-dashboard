"""SQLite persistence boundary for the Budget/finance module.

Amounts are stored as integer minor units (cents/grosze). Transaction primary
keys are random and immutable. The separate fingerprint is an import/dedupe
identity and deliberately excludes mutable annotations, bank category, and
post-transaction balance.
"""

from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from finance_importer import transaction_family


class FinanceError(RuntimeError):
    pass


class FinanceStorageError(FinanceError):
    pass


class FinanceNotFoundError(FinanceError):
    pass


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_key TEXT NOT NULL UNIQUE,
            raw_identifier TEXT NOT NULL,
            display_label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE import_batches (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
            accepted_count INTEGER NOT NULL DEFAULT 0 CHECK (accepted_count >= 0),
            duplicate_count INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_count >= 0),
            invalid_count INTEGER NOT NULL DEFAULT 0 CHECK (invalid_count >= 0),
            date_from TEXT,
            date_to TEXT,
            status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed', 'rolled_back')),
            error_summary_json TEXT NOT NULL DEFAULT '[]',
            rolled_back_at TEXT
        );

        CREATE TABLE transactions (
            id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
            created_batch_id TEXT REFERENCES import_batches(id) ON DELETE SET NULL,
            transaction_date TEXT NOT NULL,
            amount_minor INTEGER NOT NULL,
            currency TEXT NOT NULL,
            raw_description TEXT NOT NULL,
            raw_account TEXT NOT NULL,
            raw_category TEXT NOT NULL,
            raw_balance_minor INTEGER,
            merchant TEXT NOT NULL DEFAULT '',
            merchant_type TEXT NOT NULL DEFAULT '',
            user_category TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE transaction_imports (
            transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            batch_id TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
            row_number INTEGER NOT NULL CHECK (row_number > 0),
            created_by_batch INTEGER NOT NULL CHECK (created_by_batch IN (0, 1)),
            PRIMARY KEY (transaction_id, batch_id)
        );

        CREATE TABLE finance_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE legacy_migrations (
            source_key TEXT PRIMARY KEY,
            source_sha256 TEXT NOT NULL,
            backup_path TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            verification_json TEXT NOT NULL
        );

        CREATE INDEX idx_transactions_date ON transactions(transaction_date DESC, id);
        CREATE INDEX idx_transactions_account_date ON transactions(account_id, transaction_date DESC);
        CREATE INDEX idx_transactions_created_batch ON transactions(created_batch_id);
        CREATE INDEX idx_transaction_imports_batch ON transaction_imports(batch_id);
        CREATE INDEX idx_import_batches_imported_at ON import_batches(imported_at DESC);
        """,
    ),
    (
        2,
        """
        CREATE TABLE data_migrations (
            key TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL,
            verification_json TEXT NOT NULL
        );

        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            parent_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(normalized_name, parent_id)
        );

        CREATE TABLE merchant_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE merchants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            default_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            merchant_type_id INTEGER REFERENCES merchant_types(id) ON DELETE SET NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE merchant_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id INTEGER NOT NULL REFERENCES merchants(id) ON DELETE CASCADE,
            normalized_alias TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL CHECK (source IN ('migrated', 'manual', 'rule')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE classification_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 100,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            stop_processing INTEGER NOT NULL DEFAULT 0 CHECK (stop_processing IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE rule_conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL REFERENCES classification_rules(id) ON DELETE CASCADE,
            field TEXT NOT NULL,
            operator TEXT NOT NULL,
            value_text TEXT,
            value_minor INTEGER,
            position INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE rule_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL REFERENCES classification_rules(id) ON DELETE CASCADE,
            field TEXT NOT NULL,
            value_text TEXT,
            value_id INTEGER,
            position INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE review_decisions (
            transaction_id TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            issue_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('resolved', 'ignored')),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (transaction_id, issue_type)
        );

        ALTER TABLE transactions ADD COLUMN merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN merchant_type_id INTEGER REFERENCES merchant_types(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN transaction_kind TEXT CHECK (
            transaction_kind IS NULL OR transaction_kind IN
            ('expense', 'income', 'salary', 'transfer', 'refund', 'saving', 'cash', 'other')
        );
        ALTER TABLE transactions ADD COLUMN merchant_source TEXT;
        ALTER TABLE transactions ADD COLUMN category_source TEXT;
        ALTER TABLE transactions ADD COLUMN merchant_type_source TEXT;
        ALTER TABLE transactions ADD COLUMN kind_source TEXT;
        ALTER TABLE transactions ADD COLUMN merchant_rule_id INTEGER REFERENCES classification_rules(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN category_rule_id INTEGER REFERENCES classification_rules(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN merchant_type_rule_id INTEGER REFERENCES classification_rules(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN kind_rule_id INTEGER REFERENCES classification_rules(id) ON DELETE SET NULL;
        ALTER TABLE transactions ADD COLUMN classification_conflict INTEGER NOT NULL DEFAULT 0 CHECK (classification_conflict IN (0, 1));

        CREATE INDEX idx_categories_parent_sort ON categories(parent_id, sort_order, normalized_name);
        CREATE INDEX idx_merchants_type ON merchants(merchant_type_id);
        CREATE INDEX idx_merchant_aliases_normalized ON merchant_aliases(normalized_alias);
        CREATE INDEX idx_rules_order ON classification_rules(enabled, priority, id);
        CREATE INDEX idx_rule_conditions_rule ON rule_conditions(rule_id, position, id);
        CREATE INDEX idx_rule_actions_rule ON rule_actions(rule_id, position, id);
        CREATE INDEX idx_transactions_merchant_date ON transactions(merchant_id, transaction_date DESC);
        CREATE INDEX idx_transactions_category_date ON transactions(category_id, transaction_date DESC);
        CREATE INDEX idx_transactions_kind_date ON transactions(transaction_kind, transaction_date DESC);
        """,
    ),
    (
        3,
        """
        CREATE TABLE ambiguous_merchant_aliases (
            normalized_alias TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        );
        """,
    ),
    (
        4,
        """
        ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'spending'
            CHECK (role IN ('spending', 'savings', 'excluded'));
        ALTER TABLE accounts ADD COLUMN include_safe_to_spend INTEGER NOT NULL DEFAULT 1
            CHECK (include_safe_to_spend IN (0, 1));

        CREATE TABLE obligations (
            id TEXT PRIMARY KEY,
            legacy_key TEXT UNIQUE,
            name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL CHECK (kind IN (
                'bill', 'subscription', 'installment', 'rent', 'service',
                'saving', 'income', 'salary'
            )),
            display_group TEXT NOT NULL DEFAULT 'Bills',
            amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'PLN',
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            cadence TEXT NOT NULL DEFAULT 'once' CHECK (cadence IN (
                'once', 'weekly', 'monthly', 'quarterly', 'annual'
            )),
            next_expected_date TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            due_day INTEGER,
            automatic INTEGER NOT NULL DEFAULT 0 CHECK (automatic IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            confirmed INTEGER NOT NULL DEFAULT 1 CHECK (confirmed IN (0, 1)),
            essential INTEGER NOT NULL DEFAULT 0 CHECK (essential IN (0, 1)),
            installment_total_minor INTEGER,
            installment_remaining_minor INTEGER,
            installment_count INTEGER,
            installment_remaining_count INTEGER,
            note TEXT NOT NULL DEFAULT '',
            notification_json TEXT NOT NULL DEFAULT '{}',
            provenance TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE obligation_occurrences (
            id TEXT PRIMARY KEY,
            obligation_id TEXT NOT NULL REFERENCES obligations(id) ON DELETE CASCADE,
            expected_date TEXT NOT NULL,
            amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
            status TEXT NOT NULL DEFAULT 'expected' CHECK (status IN (
                'expected', 'matched', 'paid', 'overdue', 'skipped', 'dismissed'
            )),
            matched_transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
            legacy_occurrence_key TEXT UNIQUE,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(obligation_id, expected_date)
        );

        CREATE TABLE planned_items (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            planned_date TEXT NOT NULL,
            amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'PLN',
            account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            kind TEXT NOT NULL DEFAULT 'expense' CHECK (kind IN ('expense', 'income', 'saving')),
            note TEXT NOT NULL DEFAULT '',
            include_safe_to_spend INTEGER NOT NULL DEFAULT 1 CHECK (include_safe_to_spend IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'completed', 'cancelled')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
            limit_minor INTEGER NOT NULL CHECK (limit_minor >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(month, category_id)
        );

        CREATE TABLE goals (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'general' CHECK (kind IN ('general', 'emergency_fund')),
            target_minor INTEGER NOT NULL CHECK (target_minor > 0),
            allocated_minor INTEGER NOT NULL DEFAULT 0 CHECK (allocated_minor >= 0),
            currency TEXT NOT NULL DEFAULT 'PLN',
            target_date TEXT,
            linked_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
            monthly_contribution_minor INTEGER NOT NULL DEFAULT 0 CHECK (monthly_contribution_minor >= 0),
            is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX idx_obligations_active_date ON obligations(active, next_expected_date);
        CREATE INDEX idx_obligations_kind_active ON obligations(kind, active);
        CREATE INDEX idx_occurrences_date_status ON obligation_occurrences(expected_date, status);
        CREATE INDEX idx_occurrences_obligation_date ON obligation_occurrences(obligation_id, expected_date);
        CREATE INDEX idx_planned_items_date_status ON planned_items(planned_date, status);
        CREATE INDEX idx_budgets_month_category ON budgets(month, category_id);
        CREATE INDEX idx_goals_active_primary ON goals(active, is_primary);
        """,
    ),
    (
        5,
        """
        ALTER TABLE accounts ADD COLUMN match_key TEXT;
        ALTER TABLE transactions ADD COLUMN legacy_category_name TEXT NOT NULL DEFAULT '';
        ALTER TABLE transactions ADD COLUMN taxonomy_review_required INTEGER NOT NULL DEFAULT 0
            CHECK (taxonomy_review_required IN (0, 1));
        ALTER TABLE obligation_occurrences ADD COLUMN paid_at TEXT;

        CREATE TABLE category_migration_audit (
            legacy_category_id INTEGER PRIMARY KEY,
            legacy_name TEXT NOT NULL,
            canonical_category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
            mapping_status TEXT NOT NULL CHECK (mapping_status IN ('mapped', 'ambiguous')),
            transaction_count INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE classification_bootstrap_audit (
            merchant_id INTEGER PRIMARY KEY REFERENCES merchants(id) ON DELETE CASCADE,
            occurrence_count INTEGER NOT NULL,
            category_count INTEGER NOT NULL,
            kind_count INTEGER NOT NULL,
            merchant_type_count INTEGER NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX idx_accounts_match_key ON accounts(match_key)
            WHERE match_key IS NOT NULL;
        CREATE INDEX idx_transactions_taxonomy_review
            ON transactions(taxonomy_review_required, transaction_date DESC);
        """,
    ),
    (
        6,
        """
        ALTER TABLE accounts ADD COLUMN balance_minor INTEGER;
        ALTER TABLE accounts ADD COLUMN balance_as_of TEXT;
        ALTER TABLE import_batches ADD COLUMN filtered_count INTEGER NOT NULL DEFAULT 0
            CHECK (filtered_count >= 0);
        """,
    ),
    (
        7,
        """
        ALTER TABLE import_batches ADD COLUMN source_format TEXT;
        ALTER TABLE transactions ADD COLUMN import_merchant_hint TEXT NOT NULL DEFAULT '';
        CREATE TABLE account_match_aliases (
            match_key TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO account_match_aliases(match_key,account_id,created_at)
            SELECT match_key,id,updated_at FROM accounts WHERE match_key IS NOT NULL;
        CREATE INDEX idx_account_match_aliases_account ON account_match_aliases(account_id);
        """,
    ),
    (
        8,
        """
        CREATE TABLE review_bulk_actions (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            transaction_count INTEGER NOT NULL,
            fields_json TEXT NOT NULL,
            previous_json TEXT NOT NULL,
            applied_json TEXT NOT NULL,
            remember_mechanism TEXT,
            remember_entity_id INTEGER,
            created_at TEXT NOT NULL,
            undone_at TEXT
        );
        CREATE INDEX idx_review_bulk_actions_created
            ON review_bulk_actions(created_at DESC);
        """,
    ),
    (
        9,
        """
        CREATE TABLE product_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL UNIQUE,
            parent_id INTEGER REFERENCES product_categories(id) ON DELETE RESTRICT,
            finance_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE products (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            brand TEXT,
            canonical_barcode TEXT UNIQUE,
            package_quantity TEXT,
            package_unit TEXT,
            product_category_id INTEGER REFERENCES product_categories(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending', 'archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE product_barcodes (
            barcode TEXT PRIMARY KEY,
            product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            source TEXT NOT NULL DEFAULT 'manual',
            confirmed INTEGER NOT NULL DEFAULT 1 CHECK (confirmed IN (0, 1)),
            created_at TEXT NOT NULL
        );

        CREATE TABLE receipts (
            id TEXT PRIMARY KEY,
            retailer_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            retailer_key TEXT NOT NULL DEFAULT '',
            source_type TEXT NOT NULL CHECK (source_type IN ('json', 'pdf', 'image', 'ocr_text')),
            source_format TEXT NOT NULL,
            external_receipt_id TEXT,
            transaction_id TEXT REFERENCES transactions(id) ON DELETE SET NULL,
            purchase_date TEXT,
            purchase_time TEXT,
            total_minor INTEGER,
            currency TEXT NOT NULL DEFAULT 'PLN',
            store_name TEXT NOT NULL DEFAULT '',
            store_location TEXT,
            fiscal_identifier TEXT,
            parser_version TEXT NOT NULL,
            source_priority INTEGER NOT NULL DEFAULT 0,
            identity_hash TEXT,
            validation_state TEXT NOT NULL DEFAULT 'needs_review'
                CHECK (validation_state IN ('valid', 'valid_with_adjustments', 'needs_review', 'invalid')),
            validation_difference_minor INTEGER,
            match_state TEXT NOT NULL DEFAULT 'none'
                CHECK (match_state IN ('exact', 'strong', 'ambiguous', 'none', 'manual')),
            status TEXT NOT NULL DEFAULT 'inbox'
                CHECK (status IN ('inbox', 'matched', 'needs_review', 'archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE receipt_sources (
            id TEXT PRIMARY KEY,
            receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            source_sha256 TEXT NOT NULL UNIQUE,
            storage_name TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_format TEXT NOT NULL,
            source_priority INTEGER NOT NULL,
            parser_version TEXT NOT NULL,
            extracted_text TEXT,
            raw_ocr_text TEXT,
            imported_at TEXT NOT NULL
        );

        CREATE TABLE receipt_items (
            id TEXT PRIMARY KEY,
            receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            line_number INTEGER NOT NULL,
            raw_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            interpreted_name TEXT,
            raw_product_code TEXT,
            barcode TEXT,
            quantity TEXT NOT NULL DEFAULT '1',
            unit TEXT NOT NULL DEFAULT 'szt',
            unit_price_minor INTEGER,
            total_price_minor INTEGER NOT NULL,
            discount_minor INTEGER NOT NULL DEFAULT 0,
            product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
            product_category_id INTEGER REFERENCES product_categories(id) ON DELETE SET NULL,
            classification_source TEXT NOT NULL DEFAULT 'unresolved',
            review_state TEXT NOT NULL DEFAULT 'unresolved'
                CHECK (review_state IN ('unresolved', 'resolved', 'ignored')),
            confidence_state TEXT NOT NULL DEFAULT 'exact'
                CHECK (confidence_state IN ('exact', 'review', 'uncertain')),
            raw_evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(receipt_id, line_number)
        );

        CREATE TABLE receipt_adjustments (
            id TEXT PRIMARY KEY,
            receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            receipt_item_id TEXT REFERENCES receipt_items(id) ON DELETE SET NULL,
            line_number INTEGER,
            kind TEXT NOT NULL CHECK (kind IN ('discount', 'coupon', 'deposit', 'rounding', 'return', 'other')),
            label TEXT NOT NULL DEFAULT '',
            amount_minor INTEGER NOT NULL,
            raw_evidence_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE retailer_product_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            retailer_key TEXT NOT NULL,
            raw_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            retailer_code TEXT,
            alias_key TEXT NOT NULL UNIQUE,
            product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            source TEXT NOT NULL CHECK (source IN ('manual', 'guided_review', 'import', 'migration')),
            confirmed INTEGER NOT NULL DEFAULT 1 CHECK (confirmed IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE retailer_profiles (
            retailer_key TEXT PRIMARY KEY,
            retailer_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL,
            adapter_name TEXT NOT NULL,
            knowledge_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE receipt_item_bulk_actions (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            item_count INTEGER NOT NULL,
            previous_json TEXT NOT NULL,
            applied_json TEXT NOT NULL,
            alias_id INTEGER REFERENCES retailer_product_aliases(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            undone_at TEXT
        );

        CREATE TABLE finance_companion_devices (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        );

        CREATE UNIQUE INDEX idx_receipts_identity ON receipts(identity_hash)
            WHERE identity_hash IS NOT NULL;
        CREATE UNIQUE INDEX idx_receipts_transaction ON receipts(transaction_id)
            WHERE transaction_id IS NOT NULL;
        CREATE INDEX idx_receipts_date ON receipts(purchase_date DESC, id);
        CREATE INDEX idx_receipts_status ON receipts(status, validation_state, match_state);
        CREATE INDEX idx_receipt_items_receipt ON receipt_items(receipt_id, line_number);
        CREATE INDEX idx_receipt_items_review ON receipt_items(review_state, normalized_name);
        CREATE INDEX idx_receipt_items_product ON receipt_items(product_id, receipt_id);
        CREATE INDEX idx_receipt_adjustments_receipt ON receipt_adjustments(receipt_id, line_number);
        CREATE INDEX idx_product_categories_parent ON product_categories(parent_id, sort_order, name);
        CREATE INDEX idx_products_normalized ON products(normalized_name);
        CREATE INDEX idx_retailer_alias_lookup ON retailer_product_aliases(retailer_key, normalized_name, retailer_code);
        CREATE INDEX idx_companion_devices_active ON finance_companion_devices(revoked_at, created_at);
        """,
    ),
    (
        10,
        """
        ALTER TABLE receipts ADD COLUMN processing_state TEXT NOT NULL DEFAULT 'needs_review';
        ALTER TABLE receipts ADD COLUMN processing_code TEXT;
        ALTER TABLE receipts ADD COLUMN processing_message TEXT;
        ALTER TABLE receipts ADD COLUMN merchant_source TEXT NOT NULL DEFAULT 'parser';
        ALTER TABLE receipts ADD COLUMN purchase_date_source TEXT NOT NULL DEFAULT 'parser';
        ALTER TABLE receipts ADD COLUMN total_source TEXT NOT NULL DEFAULT 'parser';

        ALTER TABLE receipt_sources ADD COLUMN source_role TEXT NOT NULL DEFAULT 'primary';
        ALTER TABLE receipt_sources ADD COLUMN page_number INTEGER;
        ALTER TABLE receipt_sources ADD COLUMN ocr_provenance TEXT;
        ALTER TABLE receipt_sources ADD COLUMN processing_state TEXT NOT NULL DEFAULT 'source_received';
        ALTER TABLE receipt_sources ADD COLUMN processing_code TEXT;
        ALTER TABLE receipt_sources ADD COLUMN diagnostics_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE receipt_sources ADD COLUMN provided_ocr_text TEXT;

        UPDATE receipts
        SET processing_state = CASE
                WHEN source_format LIKE '%ocr_pending' THEN 'ocr_required'
                WHEN validation_state IN ('valid', 'valid_with_adjustments') THEN 'parsed'
                ELSE 'needs_review'
            END,
            processing_code = CASE
                WHEN source_format LIKE '%ocr_pending' THEN 'legacy_ocr_pending'
                ELSE NULL
            END,
            processing_message = CASE
                WHEN source_format LIKE '%ocr_pending' THEN 'OCR is required before this receipt can be parsed.'
                ELSE NULL
            END;

        UPDATE receipt_sources
        SET processing_state = CASE
                WHEN source_format LIKE '%ocr_pending' THEN 'ocr_required'
                WHEN source_format LIKE '%ocr%' THEN 'parsed'
                ELSE 'text_extraction'
            END,
            processing_code = CASE
                WHEN source_format LIKE '%ocr_pending' THEN 'legacy_ocr_pending'
                ELSE NULL
            END;

        CREATE INDEX idx_receipt_sources_receipt_page
            ON receipt_sources(receipt_id, source_role, page_number, imported_at);
        """,
    ),
    (
        11,
        """
        ALTER TABLE receipts ADD COLUMN field_evidence_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE receipts ADD COLUMN parse_review_json TEXT NOT NULL DEFAULT '{}';
        ALTER TABLE receipts ADD COLUMN parser_diagnostics_json TEXT NOT NULL DEFAULT '{}';

        ALTER TABLE receipt_sources ADD COLUMN ocr_structure_json TEXT NOT NULL DEFAULT '{}';

        CREATE TABLE receipt_parse_corrections (
            id TEXT PRIMARY KEY,
            receipt_id TEXT NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            previous_json TEXT NOT NULL DEFAULT '{}',
            applied_json TEXT NOT NULL DEFAULT '{}',
            source TEXT NOT NULL CHECK (source IN ('manual', 'guided_review')),
            created_at TEXT NOT NULL
        );

        CREATE INDEX idx_receipt_parse_corrections_receipt
            ON receipt_parse_corrections(receipt_id, created_at);
        """,
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_entity_name(value: Any) -> str:
    text = " ".join(str(value or "").strip().split()).casefold()
    return "".join(
        character for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )


CANONICAL_CATEGORY_TAXONOMY: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Mieszkanie", ("Czynsz", "Media", "Wyposażenie", "Chemia domowa")),
    ("Zakupy codzienne", ("Zakupy mieszane", "Spożywcze", "Używki")),
    ("Jedzenie poza domem", ("Restauracje", "Delivery", "Kawa i przekąski")),
    ("Transport", ("Komunikacja", "Taxi / rideshare", "Kolej", "Paliwo", "Inny transport")),
    ("Zdrowie", ("Apteka", "Lekarze", "Badania")),
    ("Higiena i uroda", ()),
    ("Rozrywka", ("Wydarzenia", "Gry", "Kino", "Hobby")),
    ("Usługi i subskrypcje", ("Subskrypcje", "Aplikacje", "Rachunki i usługi", "Inne usługi")),
    ("Zakupy", ("Elektronika", "Odzież", "Dom", "Inne zakupy")),
    ("Podróże", ("Noclegi", "Transport w podróży", "Inne podróże")),
    ("Edukacja", ()),
    ("Opłaty i prowizje", ()),
    ("Oszczędności", ()),
    ("Inne", ("Do ustalenia",)),
)


LEGACY_CATEGORY_MAP: dict[str, tuple[str, str | None, str]] = {
    "alkohol": ("Zakupy codzienne", "Używki", "mapped"),
    "bilety kkm": ("Transport", "Komunikacja", "mapped"),
    "dating apps subscriptions": ("Usługi i subskrypcje", "Aplikacje", "mapped"),
    "drobne zakupy": ("Zakupy codzienne", "Zakupy mieszane", "mapped"),
    "food delivery": ("Jedzenie poza domem", "Delivery", "mapped"),
    "inne": ("Inne", "Do ustalenia", "ambiguous"),
    "jedzenie": ("Zakupy codzienne", "Spożywcze", "mapped"),
    "jedzenie na miescie": ("Jedzenie poza domem", "Restauracje", "mapped"),
    "kino": ("Rozrywka", "Kino", "mapped"),
    "leki": ("Zdrowie", "Apteka", "mapped"),
    "oszczedzanie": ("Oszczędności", None, "mapped"),
    "papierosy": ("Zakupy codzienne", "Używki", "mapped"),
    "picie na miescie": ("Jedzenie poza domem", "Kawa i przekąski", "mapped"),
    "podroze": ("Podróże", "Inne podróże", "mapped"),
    "przekaski": ("Jedzenie poza domem", "Kawa i przekąski", "mapped"),
    "rachunki": ("Usługi i subskrypcje", "Rachunki i usługi", "mapped"),
    "raty": ("Inne", "Do ustalenia", "ambiguous"),
    "rozrywka": ("Rozrywka", None, "mapped"),
    "subskrypcje": ("Usługi i subskrypcje", "Subskrypcje", "mapped"),
    "transport": ("Transport", "Inny transport", "mapped"),
    "uroda": ("Higiena i uroda", None, "mapped"),
    "uslugi": ("Usługi i subskrypcje", "Inne usługi", "mapped"),
    "usługi": ("Usługi i subskrypcje", "Inne usługi", "mapped"),
    "wyplata": ("Inne", "Do ustalenia", "ambiguous"),
    "zakupy": ("Zakupy", "Inne zakupy", "mapped"),
    "zdrowie": ("Zdrowie", None, "mapped"),
}

MIXED_RETAILERS = (
    "biedronka", "zabka", "lidl", "carrefour", "auchan", "lewiatan",
    "kaufland", "aldi", "netto", "delikatesy centrum",
)


class FinanceRepository:
    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.database_path, timeout=10)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = WAL")
            return connection
        except sqlite3.DatabaseError as exc:
            raise FinanceStorageError("Finance database is unreadable or corrupt.") from exc

    def initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_version (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                applied = {
                    int(row["version"])
                    for row in connection.execute("SELECT version FROM schema_version")
                }
                for version, script in MIGRATIONS:
                    if version in applied:
                        continue
                    applied_at = utc_now().replace("'", "''")
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        f"{script}\n"
                        "INSERT INTO schema_version(version, applied_at) "
                        f"VALUES ({int(version)}, '{applied_at}');\n"
                        "COMMIT;"
                    )
            self._migrate_pack_c5_privacy()
            self._migrate_pack_b_annotations()
            self._migrate_ambiguous_aliases()
            self._migrate_pack_c5_taxonomy()
            self._bootstrap_pack_c5_classification()
        except sqlite3.DatabaseError as exc:
            raise FinanceStorageError("Finance database schema could not be initialized.") from exc

    @property
    def account_secret_path(self) -> Path:
        return self.database_path.parent / ".finance-account-key"

    def account_secret(self) -> bytes:
        path = self.account_secret_path
        if path.exists():
            secret = path.read_bytes()
            if len(secret) < 32:
                raise FinanceStorageError("Finance account fingerprint key is invalid.")
            return secret
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_bytes(32)
        try:
            with path.open("xb") as handle:
                handle.write(secret)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            return path.read_bytes()
        return secret

    @staticmethod
    def _account_match_key(raw_identifier: str, secret: bytes) -> str:
        normalized = normalize_entity_name(raw_identifier)
        canonical = re.sub(r"\s+", "", normalized)
        return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    def _migrate_pack_c5_privacy(self) -> None:
        """Replace retained own-account values with keyed matching identities."""
        secret = self.account_secret()
        backup_path: str | None = None
        with self.read_connection() as check:
            pending = int(check.execute(
                "SELECT COUNT(*) FROM accounts WHERE raw_identifier<>'' OR match_key IS NULL"
            ).fetchone()[0])
        if pending:
            backup_dir = self.database_path.parent / "budget-backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target = backup_dir / f"finance-pre-c5-privacy-{stamp}.sqlite"
            source_connection = self._connect()
            target_connection = sqlite3.connect(target)
            try:
                source_connection.backup(target_connection)
            finally:
                target_connection.close()
                source_connection.close()
            backup_path = str(target)
        with self.transaction() as connection:
            before = dict(connection.execute(
                "SELECT COUNT(*) count, COALESCE(SUM(amount_minor),0) signed FROM transactions"
            ).fetchone())
            for row in connection.execute(
                "SELECT id,account_key,raw_identifier,display_label,match_key FROM accounts ORDER BY id"
            ).fetchall():
                raw = str(row["raw_identifier"] or "")
                match_key = row["match_key"]
                if not match_key:
                    if not raw:
                        raise FinanceStorageError("An account cannot be privacy-migrated without its source identity.")
                    match_key = self._account_match_key(raw, secret)
                label = str(row["display_label"] or "")
                if not label or re.match(r"^Konto\s+(?:[•*.]+\s*)?\S{4}$", label, re.IGNORECASE):
                    label = "Konto główne"
                local_key = str(row["account_key"] or "")
                if not local_key.startswith("acct_"):
                    local_key = f"acct_{uuid.uuid4().hex}"
                connection.execute(
                    "UPDATE accounts SET account_key=?,match_key=?,raw_identifier='',display_label=?,updated_at=? WHERE id=?",
                    (local_key, match_key, label, utc_now(), row["id"]),
                )
                connection.execute("UPDATE transactions SET raw_account='' WHERE account_id=?", (row["id"],))
            connection.execute(
                "UPDATE obligation_occurrences SET paid_at=updated_at WHERE status='paid' AND paid_at IS NULL"
            )
            after = dict(connection.execute(
                "SELECT COUNT(*) count, COALESCE(SUM(amount_minor),0) signed FROM transactions"
            ).fetchone())
            retained = int(connection.execute(
                "SELECT COUNT(*) FROM accounts WHERE raw_identifier<>''"
            ).fetchone()[0]) + int(connection.execute(
                "SELECT COUNT(*) FROM transactions WHERE raw_account<>''"
            ).fetchone()[0])
            if before != after or retained:
                raise FinanceStorageError("Pack C.5 account privacy migration verification failed.")
            connection.execute(
                """INSERT INTO data_migrations(key,applied_at,verification_json) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET applied_at=excluded.applied_at,
                     verification_json=excluded.verification_json""",
                ("pack_c5_account_privacy_v1", utc_now(), json.dumps({
                    "before": before, "after": after, "retainedRawAccountFields": retained,
                    "privateBackup": backup_path,
                }, sort_keys=True)),
            )

    def _migrate_pack_b_annotations(self) -> None:
        """Normalize Pack A annotations without deleting their legacy values."""
        with self.transaction() as connection:
            marker = connection.execute(
                "SELECT verification_json FROM data_migrations WHERE key = ?",
                ("pack_b_annotations_v1",),
            ).fetchone()
            pending = int(connection.execute(
                """
                SELECT COUNT(*) FROM transactions
                WHERE (TRIM(merchant) <> '' AND merchant_id IS NULL)
                   OR (TRIM(merchant_type) <> '' AND merchant_type_id IS NULL)
                   OR (TRIM(user_category) <> '' AND category_id IS NULL)
                   OR transaction_kind IS NULL
                """
            ).fetchone()[0])
            if marker and pending == 0:
                return
            before = dict(connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(amount_minor), 0) AS signed_minor,
                       SUM(merchant <> '') AS merchant, SUM(merchant_type <> '') AS merchant_type,
                       SUM(user_category <> '') AS user_category
                FROM transactions
                """
            ).fetchone())
            now = utc_now()

            category_ids: dict[str, int] = {}
            category_rows = connection.execute(
                "SELECT id, user_category FROM transactions WHERE TRIM(user_category) <> '' ORDER BY user_category, id"
            ).fetchall()
            for row in category_rows:
                raw = " ".join(str(row["user_category"]).strip().split())
                normalized = normalize_entity_name(raw)
                if normalized not in category_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO categories(name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (raw, normalized, now, now),
                    )
                    category_ids[normalized] = int(connection.execute(
                        "SELECT id FROM categories WHERE normalized_name = ? AND parent_id IS NULL",
                        (normalized,),
                    ).fetchone()[0])
                connection.execute(
                    "UPDATE transactions SET category_id = ?, category_source = 'migrated' WHERE id = ?",
                    (category_ids[normalized], row["id"]),
                )

            type_ids: dict[str, int] = {}
            type_rows = connection.execute(
                "SELECT id, merchant_type FROM transactions WHERE TRIM(merchant_type) <> '' ORDER BY merchant_type, id"
            ).fetchall()
            for row in type_rows:
                raw = " ".join(str(row["merchant_type"]).strip().split())
                normalized = normalize_entity_name(raw)
                if normalized not in type_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO merchant_types(name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (raw, normalized, now, now),
                    )
                    type_ids[normalized] = int(connection.execute(
                        "SELECT id FROM merchant_types WHERE normalized_name = ?", (normalized,)
                    ).fetchone()[0])
                connection.execute(
                    "UPDATE transactions SET merchant_type_id = ?, merchant_type_source = 'migrated' WHERE id = ?",
                    (type_ids[normalized], row["id"]),
                )

            merchant_ids: dict[str, int] = {}
            merchant_rows = connection.execute(
                "SELECT id, merchant, raw_description FROM transactions WHERE TRIM(merchant) <> '' ORDER BY merchant, id"
            ).fetchall()
            for row in merchant_rows:
                raw = " ".join(str(row["merchant"]).strip().split())
                normalized = normalize_entity_name(raw)
                if normalized not in merchant_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO merchants(canonical_name, normalized_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        (raw, normalized, now, now),
                    )
                    merchant_ids[normalized] = int(connection.execute(
                        "SELECT id FROM merchants WHERE normalized_name = ?", (normalized,)
                    ).fetchone()[0])
                merchant_id = merchant_ids[normalized]
                connection.execute(
                    "UPDATE transactions SET merchant_id = ?, merchant_source = 'migrated' WHERE id = ?",
                    (merchant_id, row["id"]),
                )
                alias = normalize_entity_name(row["raw_description"])
                if alias:
                    ambiguous = connection.execute(
                        "SELECT 1 FROM ambiguous_merchant_aliases WHERE normalized_alias=?", (alias,)
                    ).fetchone()
                    existing_alias = connection.execute(
                        "SELECT merchant_id FROM merchant_aliases WHERE normalized_alias=?", (alias,)
                    ).fetchone()
                    if not ambiguous and existing_alias and int(existing_alias["merchant_id"]) != merchant_id:
                        connection.execute("DELETE FROM merchant_aliases WHERE normalized_alias=?", (alias,))
                        connection.execute(
                            "INSERT OR IGNORE INTO ambiguous_merchant_aliases(normalized_alias, created_at) VALUES (?, ?)",
                            (alias, now),
                        )
                    elif not ambiguous and not existing_alias:
                        connection.execute(
                            "INSERT INTO merchant_aliases(merchant_id, normalized_alias, source, created_at, updated_at) VALUES (?, ?, 'migrated', ?, ?)",
                            (merchant_id, alias, now, now),
                        )

            connection.execute(
                """
                UPDATE merchants SET merchant_type_id = (
                    SELECT t.merchant_type_id FROM transactions t
                    WHERE t.merchant_id = merchants.id AND t.merchant_type_id IS NOT NULL
                    GROUP BY t.merchant_type_id
                    ORDER BY COUNT(*) DESC, t.merchant_type_id LIMIT 1
                )
                """
            )
            connection.execute(
                """
                UPDATE merchants SET default_category_id = (
                    SELECT t.category_id FROM transactions t
                    WHERE t.merchant_id = merchants.id AND t.category_id IS NOT NULL
                    GROUP BY t.category_id
                    ORDER BY COUNT(*) DESC, t.category_id LIMIT 1
                )
                """
            )
            connection.execute(
                """
                UPDATE transactions
                SET transaction_kind = CASE WHEN amount_minor < 0 THEN 'expense' ELSE 'other' END,
                    kind_source = 'system_fallback'
                WHERE transaction_kind IS NULL
                """
            )
            after = dict(connection.execute(
                """
                SELECT COUNT(*) AS count, COALESCE(SUM(amount_minor), 0) AS signed_minor,
                       SUM(merchant_id IS NOT NULL) AS merchant,
                       SUM(merchant_type_id IS NOT NULL) AS merchant_type,
                       SUM(category_id IS NOT NULL) AS user_category
                FROM transactions
                """
            ).fetchone())
            if before != after:
                raise FinanceStorageError("Pack B annotation migration verification failed.")
            connection.execute(
                """
                INSERT INTO data_migrations(key, applied_at, verification_json) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET applied_at=excluded.applied_at,
                    verification_json=excluded.verification_json
                """,
                ("pack_b_annotations_v1", now, json.dumps({"before": before, "after": after}, sort_keys=True)),
            )

    def _migrate_ambiguous_aliases(self) -> None:
        with self.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM data_migrations WHERE key='pack_b_ambiguous_aliases_v1'"
            ).fetchone():
                return
            candidates: dict[str, set[int]] = {}
            for row in connection.execute(
                "SELECT raw_description, merchant_id FROM transactions WHERE merchant_id IS NOT NULL"
            ):
                alias = normalize_entity_name(row["raw_description"])
                if alias:
                    candidates.setdefault(alias, set()).add(int(row["merchant_id"]))
            ambiguous = sorted(alias for alias, merchant_ids in candidates.items() if len(merchant_ids) > 1)
            now = utc_now()
            for alias in ambiguous:
                connection.execute("DELETE FROM merchant_aliases WHERE normalized_alias=?", (alias,))
                connection.execute(
                    "INSERT OR IGNORE INTO ambiguous_merchant_aliases(normalized_alias, created_at) VALUES (?, ?)",
                    (alias, now),
                )
            connection.execute(
                "INSERT INTO data_migrations(key, applied_at, verification_json) VALUES (?, ?, ?)",
                ("pack_b_ambiguous_aliases_v1", now, json.dumps({"ambiguousAliasCount": len(ambiguous)})),
            )

    @staticmethod
    def _ensure_category(
        connection: sqlite3.Connection, name: str, parent_id: int | None = None, sort_order: int = 0
    ) -> int:
        normalized = normalize_entity_name(name)
        row = connection.execute(
            "SELECT id FROM categories WHERE normalized_name=? AND parent_id IS ?",
            (normalized, parent_id),
        ).fetchone()
        if row:
            connection.execute("UPDATE categories SET is_active=1 WHERE id=?", (row["id"],))
            return int(row["id"])
        now = utc_now()
        cursor = connection.execute(
            """INSERT INTO categories(name,normalized_name,parent_id,sort_order,created_at,updated_at)
               VALUES (?,?,?,?,?,?)""",
            (name, normalized, parent_id, sort_order, now, now),
        )
        return int(cursor.lastrowid)

    def _migrate_pack_c5_taxonomy(self) -> None:
        """Map free-form historical categories into the canonical two-level taxonomy."""
        with self.transaction() as connection:
            category_ids: dict[tuple[str, str | None], int] = {}
            for top_order, (top_name, children) in enumerate(CANONICAL_CATEGORY_TAXONOMY, 1):
                top_id = self._ensure_category(connection, top_name, sort_order=top_order * 10)
                category_ids[(top_name, None)] = top_id
                for child_order, child_name in enumerate(children, 1):
                    category_ids[(top_name, child_name)] = self._ensure_category(
                        connection, child_name, top_id, child_order
                    )

            pending = connection.execute(
                """SELECT DISTINCT c.id,c.name FROM transactions t JOIN categories c ON c.id=t.category_id
                   WHERE t.category_source='migrated' AND t.legacy_category_name=''"""
            ).fetchall()
            before = dict(connection.execute(
                """SELECT COUNT(*) count,COALESCE(SUM(amount_minor),0) signed,
                          SUM(category_id IS NOT NULL) categorized FROM transactions"""
            ).fetchone())
            mapped_transactions = 0
            ambiguous_transactions = 0
            for legacy in pending:
                normalized = normalize_entity_name(legacy["name"])
                top, child, status = LEGACY_CATEGORY_MAP.get(
                    normalized, ("Inne", "Do ustalenia", "ambiguous")
                )
                target_id = category_ids[(top, child)]
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM transactions WHERE category_id=? AND category_source='migrated' AND legacy_category_name=''",
                    (legacy["id"],),
                ).fetchone()[0])
                connection.execute(
                    """UPDATE transactions SET legacy_category_name=?,category_id=?,
                           taxonomy_review_required=?,updated_at=?
                       WHERE category_id=? AND category_source='migrated' AND legacy_category_name=''""",
                    (legacy["name"], target_id, int(status == "ambiguous"), utc_now(), legacy["id"]),
                )
                if normalized == "oszczedzanie":
                    connection.execute(
                        """UPDATE transactions SET transaction_kind='saving',kind_source='migrated',updated_at=?
                           WHERE legacy_category_name=?""",
                        (utc_now(), legacy["name"]),
                    )
                connection.execute(
                    """INSERT INTO category_migration_audit(
                           legacy_category_id,legacy_name,canonical_category_id,mapping_status,transaction_count,applied_at
                       ) VALUES (?,?,?,?,?,?)
                       ON CONFLICT(legacy_category_id) DO UPDATE SET
                         legacy_name=excluded.legacy_name,canonical_category_id=excluded.canonical_category_id,
                         mapping_status=excluded.mapping_status,transaction_count=excluded.transaction_count,
                         applied_at=excluded.applied_at""",
                    (legacy["id"], legacy["name"], target_id, status, count, utc_now()),
                )
                mapped_transactions += count
                if status == "ambiguous":
                    ambiguous_transactions += count

            # Reconcile mappings when the canonical policy itself is refined.
            for audit in connection.execute(
                "SELECT * FROM category_migration_audit"
            ).fetchall():
                normalized = normalize_entity_name(audit["legacy_name"])
                target = LEGACY_CATEGORY_MAP.get(normalized)
                if not target:
                    continue
                top, child, status = target
                target_id = category_ids[(top, child)]
                if target_id == audit["canonical_category_id"] and status == audit["mapping_status"]:
                    continue
                connection.execute(
                    """UPDATE transactions SET category_id=?,taxonomy_review_required=?,updated_at=?
                       WHERE legacy_category_name=? AND category_source='migrated'""",
                    (target_id, int(status == "ambiguous"), utc_now(), audit["legacy_name"]),
                )
                connection.execute(
                    """UPDATE category_migration_audit SET canonical_category_id=?,mapping_status=?,applied_at=?
                       WHERE legacy_category_id=?""",
                    (target_id, status, utc_now(), audit["legacy_category_id"]),
                )

            # Mixed retailers never inherit a product-level category from bank history.
            mixed_id = category_ids[("Zakupy codzienne", "Zakupy mieszane")]
            for row in connection.execute("SELECT id,normalized_name FROM merchants").fetchall():
                if any(token in str(row["normalized_name"]) for token in MIXED_RETAILERS):
                    connection.execute(
                        """UPDATE transactions SET category_id=?,updated_at=?
                           WHERE merchant_id=? AND category_source='migrated'""",
                        (mixed_id, utc_now(), row["id"]),
                    )

            legacy_ids = [int(row["id"]) for row in pending]
            if legacy_ids:
                placeholders = ",".join("?" for _ in legacy_ids)
                connection.execute(
                    f"UPDATE categories SET is_active=0,updated_at=? WHERE id IN ({placeholders}) AND id NOT IN (SELECT canonical_category_id FROM category_migration_audit)",
                    (utc_now(), *legacy_ids),
                )
            after = dict(connection.execute(
                """SELECT COUNT(*) count,COALESCE(SUM(amount_minor),0) signed,
                          SUM(category_id IS NOT NULL) categorized FROM transactions"""
            ).fetchone())
            if before != after:
                raise FinanceStorageError("Pack C.5 category migration verification failed.")
            connection.execute(
                """INSERT INTO data_migrations(key,applied_at,verification_json) VALUES (?,?,?)
                   ON CONFLICT(key) DO UPDATE SET applied_at=excluded.applied_at,
                     verification_json=excluded.verification_json""",
                ("pack_c5_taxonomy_v1", utc_now(), json.dumps({
                    "before": before, "after": after,
                    "mappedTransactions": mapped_transactions,
                    "ambiguousTransactions": ambiguous_transactions,
                }, ensure_ascii=False, sort_keys=True)),
            )

    def _bootstrap_pack_c5_classification(self) -> None:
        """Create only strict merchant defaults; retain all other patterns as review evidence."""
        with self.transaction() as connection:
            now = utc_now()
            rows = connection.execute(
                """SELECT m.id,COUNT(*) occurrence_count,
                          COUNT(DISTINCT t.category_id) category_count,
                          COUNT(DISTINCT t.transaction_kind) kind_count,
                          COUNT(DISTINCT t.merchant_type_id) merchant_type_count,
                          MIN(t.category_id) category_id
                   FROM merchants m JOIN transactions t ON t.merchant_id=m.id
                   GROUP BY m.id"""
            ).fetchall()
            for row in rows:
                count = int(row["occurrence_count"])
                safe = count >= 3 and int(row["category_count"]) == 1 and row["category_id"] is not None \
                    and int(row["kind_count"]) == 1 and int(row["merchant_type_count"]) <= 1
                decision = "merchant_default" if safe else "review"
                reason = (
                    f"{count} zgodnych historycznych transakcji; ustawiono bezpieczną wartość domyślną."
                    if safe else "Historia nie spełnia progu: minimum 3 i pełna zgodność miejsca, kategorii oraz rodzaju."
                )
                if safe:
                    connection.execute(
                        "UPDATE merchants SET default_category_id=?,updated_at=? WHERE id=?",
                        (row["category_id"], now, row["id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE merchants SET default_category_id=NULL,updated_at=? WHERE id=?",
                        (now, row["id"]),
                    )
                connection.execute(
                    """INSERT INTO classification_bootstrap_audit(
                         merchant_id,occurrence_count,category_count,kind_count,merchant_type_count,
                         decision,reason,updated_at) VALUES (?,?,?,?,?,?,?,?)
                       ON CONFLICT(merchant_id) DO UPDATE SET
                         occurrence_count=excluded.occurrence_count,category_count=excluded.category_count,
                         kind_count=excluded.kind_count,merchant_type_count=excluded.merchant_type_count,
                         decision=excluded.decision,reason=excluded.reason,updated_at=excluded.updated_at""",
                    (row["id"], count, row["category_count"], row["kind_count"],
                     row["merchant_type_count"], decision, reason, now),
                )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def schema_versions(self) -> list[int]:
        with self._connect() as connection:
            return [int(row[0]) for row in connection.execute(
                "SELECT version FROM schema_version ORDER BY version"
            )]

    def transaction_count(self, connection: sqlite3.Connection | None = None) -> int:
        if connection is not None:
            return int(connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        with self._connect() as own_connection:
            return int(own_connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])

    def create_batch(self, filename: str, imported_at: str | None = None) -> str:
        batch_id = f"imp_{uuid.uuid4().hex}"
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO import_batches(id, filename, imported_at, status) VALUES (?, ?, ?, 'pending')",
                (batch_id, filename, imported_at or utc_now()),
            )
        return batch_id

    def finish_batch(
        self,
        batch_id: str,
        *,
        status: str,
        row_count: int,
        accepted_count: int,
        duplicate_count: int,
        invalid_count: int,
        filtered_count: int,
        source_format: str | None,
        date_from: str | None,
        date_to: str | None,
        errors: list[dict[str, Any]],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        target = connection or self._connect()
        try:
            result = target.execute(
                """
                UPDATE import_batches
                SET status = ?, row_count = ?, accepted_count = ?, duplicate_count = ?,
                    invalid_count = ?, filtered_count = ?, source_format = ?, date_from = ?, date_to = ?, error_summary_json = ?
                WHERE id = ?
                """,
                (
                    status,
                    row_count,
                    accepted_count,
                    duplicate_count,
                    invalid_count,
                    filtered_count,
                    source_format,
                    date_from,
                    date_to,
                    json.dumps(errors, ensure_ascii=False),
                    batch_id,
                ),
            )
            if result.rowcount != 1:
                raise FinanceNotFoundError("Import batch was not found.")
            if connection is None:
                target.commit()
        finally:
            if connection is None:
                target.close()

    def resolve_account(
        self,
        connection: sqlite3.Connection,
        *,
        match_key: str,
        display_label: str,
        role: str = "spending",
        include_safe_to_spend: bool = True,
        alias_existing: bool = False,
    ) -> int:
        now = utc_now()
        row = connection.execute(
            """SELECT a.id FROM account_match_aliases ama
               JOIN accounts a ON a.id=ama.account_id WHERE ama.match_key=?
               UNION SELECT id FROM accounts WHERE match_key=? LIMIT 1""",
            (match_key, match_key),
        ).fetchone()
        if row:
            connection.execute(
                "INSERT OR IGNORE INTO account_match_aliases(match_key,account_id,created_at) VALUES (?,?,?)",
                (match_key, row["id"], now),
            )
            connection.execute("UPDATE accounts SET updated_at=? WHERE id=?", (now, row["id"]))
            return int(row["id"])
        candidates = connection.execute(
            "SELECT id FROM accounts WHERE role=? AND display_label=? ORDER BY id",
            (role, display_label),
        ).fetchall() if alias_existing else []
        if len(candidates) == 1:
            account_id = int(candidates[0]["id"])
            connection.execute(
                "INSERT INTO account_match_aliases(match_key,account_id,created_at) VALUES (?,?,?)",
                (match_key, account_id, now),
            )
            connection.execute("UPDATE accounts SET updated_at=? WHERE id=?", (now, account_id))
            return account_id
        account_key = f"acct_{uuid.uuid4().hex}"
        account_count = int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
        default_label = "Konto główne" if account_count == 0 else f"Konto {account_count + 1}"
        requested_label = " ".join(str(display_label or "").split())[:120]
        if requested_label and requested_label != "Konto główne":
            default_label = requested_label
            suffix = 2
            while connection.execute(
                "SELECT 1 FROM accounts WHERE display_label=?", (default_label,)
            ).fetchone():
                default_label = f"{requested_label} {suffix}"
                suffix += 1
        connection.execute(
            """INSERT INTO accounts(
                   account_key,match_key,raw_identifier,display_label,role,include_safe_to_spend,
                   created_at,updated_at
               ) VALUES (?,?, '', ?,?,?,?,?)""",
            (account_key, match_key, default_label, role, int(include_safe_to_spend), now, now),
        )
        row = connection.execute(
            "SELECT id FROM accounts WHERE match_key = ?", (match_key,)
        ).fetchone()
        connection.execute(
            "INSERT OR IGNORE INTO account_match_aliases(match_key,account_id,created_at) VALUES (?,?,?)",
            (match_key, row["id"], now),
        )
        return int(row["id"])

    @staticmethod
    def update_account_balance(
        connection: sqlite3.Connection,
        account_id: int,
        *,
        balance_minor: int,
        balance_as_of: str,
    ) -> None:
        connection.execute(
            """UPDATE accounts SET balance_minor=?,balance_as_of=?,updated_at=?
               WHERE id=? AND (balance_as_of IS NULL OR balance_as_of<=?)""",
            (balance_minor, balance_as_of, utc_now(), account_id, balance_as_of),
        )

    def find_transaction_id(
        self, connection: sqlite3.Connection, fingerprint: str, *,
        transaction: dict[str, Any] | None = None, account_id: int | None = None,
        batch_id: str | None = None, source_format: str | None = None,
    ) -> str | None:
        row = connection.execute(
            "SELECT id FROM transactions WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if not row and transaction is not None and account_id is not None:
            occurrence = max(1, int(transaction.get("occurrence") or 1))
            row = connection.execute(
                """SELECT t.id FROM transactions t
                   WHERE t.account_id=? AND t.transaction_date=? AND t.amount_minor=?
                     AND t.currency=? AND t.raw_description=?
                   ORDER BY COALESCE((SELECT MIN(ti.row_number) FROM transaction_imports ti
                                      WHERE ti.transaction_id=t.id),2147483647),t.id
                   LIMIT 1 OFFSET ?""",
                (account_id, transaction["transaction_date"], transaction["amount_minor"],
                 transaction["currency"], transaction["raw_description"], occurrence - 1),
            ).fetchone()
        if not row and transaction is not None and account_id is not None and batch_id:
            family = transaction_family(
                transaction["raw_description"], transaction.get("raw_category", "")
            )
            if family != "other":
                center = datetime.fromisoformat(transaction["transaction_date"]).date()
                date_from = (center - timedelta(days=2)).isoformat()
                date_to = (center + timedelta(days=2)).isoformat()
                candidates = connection.execute(
                    """SELECT t.id,t.transaction_date,t.raw_description,t.raw_category,
                              ib.source_format,
                              COALESCE((SELECT MIN(ti.row_number) FROM transaction_imports ti
                                        WHERE ti.transaction_id=t.id),2147483647) first_row
                       FROM transactions t
                       LEFT JOIN import_batches ib ON ib.id=t.created_batch_id
                       WHERE t.account_id=? AND t.amount_minor=? AND t.currency=?
                         AND t.transaction_date BETWEEN ? AND ?
                         AND NOT EXISTS (
                           SELECT 1 FROM transaction_imports used
                           WHERE used.transaction_id=t.id AND used.batch_id=?
                         )
                       ORDER BY ABS(julianday(t.transaction_date)-julianday(?)),first_row,t.id""",
                    (
                        account_id,
                        transaction["amount_minor"],
                        transaction["currency"],
                        date_from,
                        date_to,
                        batch_id,
                        transaction["transaction_date"],
                    ),
                ).fetchall()
                row = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate["source_format"] != source_format
                        and transaction_family(
                            candidate["raw_description"], candidate["raw_category"]
                        ) == family
                    ),
                    None,
                )
        return str(row["id"]) if row else None

    def insert_transaction(
        self,
        connection: sqlite3.Connection,
        transaction: dict[str, Any],
        *,
        account_id: int,
        batch_id: str,
    ) -> str:
        transaction_id = f"tx_{uuid.uuid4().hex}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO transactions(
                id, fingerprint, account_id, created_batch_id, transaction_date,
                amount_minor, currency, raw_description, raw_account, raw_category,
                raw_balance_minor, merchant, merchant_type, user_category, note, import_merchant_hint,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                transaction["fingerprint"],
                account_id,
                batch_id,
                transaction["transaction_date"],
                transaction["amount_minor"],
                transaction["currency"],
                transaction["raw_description"],
                "",
                transaction["raw_category"],
                transaction.get("raw_balance_minor"),
                transaction.get("merchant", ""),
                transaction.get("merchant_type", ""),
                transaction.get("user_category", ""),
                transaction.get("note", ""),
                transaction.get("merchant_hint", ""),
                now,
                now,
            ),
        )
        return transaction_id

    def associate_import(
        self,
        connection: sqlite3.Connection,
        *,
        transaction_id: str,
        batch_id: str,
        row_number: int,
        created_by_batch: bool,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO transaction_imports(
                transaction_id, batch_id, row_number, created_by_batch
            ) VALUES (?, ?, ?, ?)
            """,
            (transaction_id, batch_id, row_number, int(created_by_batch)),
        )

    def list_transactions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, a.display_label AS account_display,
                       m.canonical_name AS merchant_name,
                       c.name AS category_name,
                       pc.name AS parent_category_name,
                       mt.name AS merchant_type_name
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                LEFT JOIN merchants m ON m.id = t.merchant_id
                LEFT JOIN categories c ON c.id = t.category_id
                LEFT JOIN categories pc ON pc.id = c.parent_id
                LEFT JOIN merchant_types mt ON mt.id = t.merchant_type_id
                ORDER BY t.transaction_date DESC, ABS(t.amount_minor) DESC, t.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def query_transactions(
        self,
        *,
        page: int = 1,
        limit: int = 50,
        date_from: str | None = None,
        date_to: str | None = None,
        account_id: int | None = None,
        category_id: int | None = None,
        merchant_id: int | None = None,
        merchant_type_id: int | None = None,
        transaction_kind: str | None = None,
        amount_min_minor: int | None = None,
        amount_max_minor: int | None = None,
        text: str | None = None,
        sort: str = "date_desc",
    ) -> dict[str, Any]:
        page = max(1, int(page))
        limit = max(1, min(200, int(limit)))
        clauses: list[str] = []
        params: list[Any] = []
        for column, value, operator in (
            ("t.transaction_date", date_from, ">="),
            ("t.transaction_date", date_to, "<="),
            ("t.account_id", account_id, "="),
            ("t.category_id", category_id, "="),
            ("t.merchant_id", merchant_id, "="),
            ("t.merchant_type_id", merchant_type_id, "="),
            ("t.transaction_kind", transaction_kind, "="),
        ):
            if value is not None and value != "":
                clauses.append(f"{column} {operator} ?")
                params.append(value)
        if amount_min_minor is not None:
            clauses.append("t.amount_minor >= ?")
            params.append(amount_min_minor)
        if amount_max_minor is not None:
            clauses.append("t.amount_minor <= ?")
            params.append(amount_max_minor)
        if text:
            clauses.append(
                "(t.raw_description LIKE ? ESCAPE '\\' OR m.canonical_name LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\')"
            )
            escaped = str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend([f"%{escaped}%"] * 3)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        order = {
            "date_desc": "t.transaction_date DESC, t.id",
            "date_asc": "t.transaction_date ASC, t.id",
            "amount_desc": "t.amount_minor DESC, t.id",
            "amount_asc": "t.amount_minor ASC, t.id",
        }.get(sort, "t.transaction_date DESC, t.id")
        with self._connect() as connection:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id LEFT JOIN categories c ON c.id=t.category_id {where}",
                params,
            ).fetchone()[0])
            rows = connection.execute(
                f"""
                SELECT t.*, a.display_label AS account_display,
                       m.canonical_name AS merchant_name, c.name AS category_name,
                       pc.name AS parent_category_name, mt.name AS merchant_type_name
                FROM transactions t JOIN accounts a ON a.id=t.account_id
                LEFT JOIN merchants m ON m.id=t.merchant_id
                LEFT JOIN categories c ON c.id=t.category_id
                LEFT JOIN categories pc ON pc.id=c.parent_id
                LEFT JOIN merchant_types mt ON mt.id=t.merchant_type_id
                {where} ORDER BY {order} LIMIT ? OFFSET ?
                """,
                (*params, limit, (page - 1) * limit),
            ).fetchall()
        return {"rows": [dict(row) for row in rows], "page": page, "limit": limit, "total": total}

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id,display_label,role,include_safe_to_spend,balance_minor,balance_as_of,
                          created_at,updated_at FROM accounts ORDER BY id"""
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS transaction_count,
                       MIN(transaction_date) AS date_from,
                       MAX(transaction_date) AS date_to,
                       COALESCE(SUM(amount_minor), 0) AS signed_minor,
                       COALESCE(SUM(CASE WHEN amount_minor < 0 THEN amount_minor ELSE 0 END), 0) AS negative_minor,
                       COALESCE(SUM(CASE WHEN amount_minor > 0 THEN amount_minor ELSE 0 END), 0) AS positive_minor
                FROM transactions
                """
            ).fetchone()
        return dict(row)

    def list_batches(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM import_batches
                ORDER BY imported_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, min(500, int(limit))),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["errors"] = json.loads(item.pop("error_summary_json") or "[]")
            result.append(item)
        return result

    def latest_completed_batch(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM import_batches
                WHERE status = 'completed'
                ORDER BY imported_at DESC, id DESC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def rollback_batch(self, batch_id: str) -> dict[str, int | str]:
        """Detach a batch and delete only transactions unique to that batch."""
        with self.transaction() as connection:
            batch = connection.execute(
                "SELECT id, status FROM import_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if not batch:
                raise FinanceNotFoundError("Import batch was not found.")
            if batch["status"] == "rolled_back":
                return {"batchId": batch_id, "deleted": 0, "detached": 0}
            if batch["status"] != "completed":
                raise FinanceError("Only a completed import batch can be rolled back.")

            associations = connection.execute(
                """
                SELECT transaction_id, created_by_batch
                FROM transaction_imports WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchall()
            deleted = 0
            detached = 0
            for association in associations:
                transaction_id = str(association["transaction_id"])
                other = connection.execute(
                    """
                    SELECT ti.batch_id
                    FROM transaction_imports ti
                    JOIN import_batches ib ON ib.id = ti.batch_id
                    WHERE ti.transaction_id = ? AND ti.batch_id <> ?
                      AND ib.status = 'completed'
                    ORDER BY ib.imported_at, ib.id
                    LIMIT 1
                    """,
                    (transaction_id, batch_id),
                ).fetchone()
                if association["created_by_batch"] and not other:
                    connection.execute(
                        "DELETE FROM transactions WHERE id = ?", (transaction_id,)
                    )
                    deleted += 1
                    continue
                connection.execute(
                    "DELETE FROM transaction_imports WHERE transaction_id = ? AND batch_id = ?",
                    (transaction_id, batch_id),
                )
                if other:
                    connection.execute(
                        """
                        UPDATE transactions
                        SET created_batch_id = ?, updated_at = ?
                        WHERE id = ? AND created_batch_id = ?
                        """,
                        (other["batch_id"], utc_now(), transaction_id, batch_id),
                    )
                detached += 1
            connection.execute(
                "UPDATE import_batches SET status = 'rolled_back', rolled_back_at = ? WHERE id = ?",
                (utc_now(), batch_id),
            )
        return {"batchId": batch_id, "deleted": deleted, "detached": detached}

    def rollback_preview(self, batch_id: str) -> dict[str, int | str]:
        with self.read_connection() as connection:
            batch = connection.execute("SELECT id,status FROM import_batches WHERE id=?", (batch_id,)).fetchone()
            if not batch:
                raise FinanceNotFoundError("Import batch was not found.")
            row = connection.execute(
                """SELECT COUNT(*) associated,
                   SUM(CASE WHEN ti.created_by_batch=1 AND NOT EXISTS (
                     SELECT 1 FROM transaction_imports other
                     JOIN import_batches ib ON ib.id=other.batch_id
                     WHERE other.transaction_id=ti.transaction_id AND other.batch_id<>ti.batch_id
                       AND ib.status='completed') THEN 1 ELSE 0 END) deletable,
                   SUM(CASE WHEN (t.merchant_source IN ('manual','migrated') OR
                                      t.category_source IN ('manual','migrated') OR
                                      t.kind_source IN ('manual','migrated') OR TRIM(t.note)<>'')
                            THEN 1 ELSE 0 END) annotated
                   FROM transaction_imports ti JOIN transactions t ON t.id=ti.transaction_id
                   WHERE ti.batch_id=?""", (batch_id,)
            ).fetchone()
        associated = int(row["associated"] or 0); deletable = int(row["deletable"] or 0)
        return {"batchId": batch_id, "status": batch["status"], "associated": associated,
                "deleted": deletable, "detached": associated - deletable, "annotated": int(row["annotated"] or 0)}

    def read_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value_json FROM finance_settings").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            result[str(row["key"])] = json.loads(row["value_json"])
        return result

    def update_annotations(
        self, updates: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        with self.transaction() as connection:
            for update in updates:
                transaction_id = str(update.get("id") or "")
                result = connection.execute(
                    """
                    UPDATE transactions
                    SET merchant = ?, merchant_type = ?, user_category = ?, note = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(update.get("merchant") or ""),
                        str(update.get("merchantType") or ""),
                        str(update.get("userCategory") or ""),
                        str(update.get("note") or ""),
                        utc_now(),
                        transaction_id,
                    ),
                )
                if result.rowcount != 1:
                    raise FinanceNotFoundError("Transaction was not found.")
                row = connection.execute(
                    """
                    SELECT id, merchant, merchant_type, user_category, note, updated_at
                    FROM transactions WHERE id = ?
                    """,
                    (transaction_id,),
                ).fetchone()
                changed.append(dict(row))
        return changed

    def write_settings(
        self,
        settings: dict[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        target = connection or self._connect()
        try:
            now = utc_now()
            for key, value in settings.items():
                target.execute(
                    """
                    INSERT INTO finance_settings(key, value_json, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (str(key), json.dumps(value, ensure_ascii=False), now),
                )
            if connection is None:
                target.commit()
        finally:
            if connection is None:
                target.close()

    def legacy_migration(self, source_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM legacy_migrations WHERE source_key = ?", (source_key,)
            ).fetchone()
        return dict(row) if row else None

    def record_legacy_migration(
        self,
        connection: sqlite3.Connection,
        *,
        source_key: str,
        source_sha256: str,
        backup_path: str,
        verification: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO legacy_migrations(
                source_key, source_sha256, backup_path, migrated_at, verification_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                source_key,
                source_sha256,
                backup_path,
                utc_now(),
                json.dumps(verification, ensure_ascii=False, sort_keys=True),
            ),
        )
