-- ============================================================
-- Meridian — Complete Schema (Section 4 of system design)
-- ============================================================
CREATE DATABASE IF NOT EXISTS meridian
    CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE meridian;

-- ============================================================
-- persons — the contact database
-- ============================================================
CREATE TABLE IF NOT EXISTS persons (
    id                  BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name           VARCHAR(150)    NOT NULL,
    email               VARCHAR(255)    NOT NULL,
    designation         VARCHAR(150)    NOT NULL,
    category            ENUM(
                            'billionaire','millionaire','tech_founder','politician',
                            'content_creator','journalist','human_rights','government_org',
                            'government_official','diplomat','media_personality',
                            'united_organization','high_value_person','other'
                        ) NOT NULL DEFAULT 'other',
    organization        VARCHAR(200)    NULL,
    country             VARCHAR(100)    NULL,
    preferred_tone      ENUM('professional','semi_casual','casual','auto') NOT NULL DEFAULT 'auto',
    notes               TEXT            NULL,
    status              ENUM('active','unsubscribed','bounced','archived') NOT NULL DEFAULT 'active',
    created_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_persons_email (email),
    KEY idx_persons_category (category),
    KEY idx_persons_status (status)
) ENGINE=InnoDB;

-- ============================================================
-- tone_settings — professionality mix (must sum to 100)
-- ============================================================
CREATE TABLE IF NOT EXISTS tone_settings (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    professional_percent    TINYINT UNSIGNED NOT NULL DEFAULT 60,
    semi_casual_percent     TINYINT UNSIGNED NOT NULL DEFAULT 30,
    casual_percent          TINYINT UNSIGNED NOT NULL DEFAULT 10,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by_note         VARCHAR(255) NULL,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================================
-- campaigns — one batch/run of sends
-- ============================================================
CREATE TABLE IF NOT EXISTS campaigns (
    id                          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name                        VARCHAR(200) NOT NULL,
    topic_brief                 TEXT NOT NULL,
    target_filter               VARCHAR(255) NULL,
    tone_professional_percent   TINYINT UNSIGNED NOT NULL,
    tone_semi_casual_percent    TINYINT UNSIGNED NOT NULL,
    tone_casual_percent         TINYINT UNSIGNED NOT NULL,
    total_recipients            INT UNSIGNED NOT NULL DEFAULT 0,
    total_sent                  INT UNSIGNED NOT NULL DEFAULT 0,
    total_failed                INT UNSIGNED NOT NULL DEFAULT 0,
    status                      ENUM('draft','in_progress','completed','aborted') NOT NULL DEFAULT 'draft',
    created_at                  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at                TIMESTAMP NULL
) ENGINE=InnoDB;

-- ============================================================
-- message_log — full send-level audit trail
-- ============================================================
CREATE TABLE IF NOT EXISTS message_log (
    id                      BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    campaign_id             BIGINT UNSIGNED NULL,
    person_id               BIGINT UNSIGNED NOT NULL,
    recipient_email         VARCHAR(255) NOT NULL,
    recipient_name          VARCHAR(150) NOT NULL,
    designation_snapshot    VARCHAR(150) NOT NULL,
    subject                 VARCHAR(255) NOT NULL,
    message_body            TEXT NOT NULL,
    word_count              SMALLINT UNSIGNED NOT NULL,
    tone_used               ENUM('professional','semi_casual','casual') NOT NULL,
    resend_message_id       VARCHAR(100) NULL,
    status                  ENUM('pending','sent','failed','skipped') NOT NULL DEFAULT 'pending',
    error_message           TEXT NULL,
    sent_at                 TIMESTAMP NULL,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_msglog_person   FOREIGN KEY (person_id)   REFERENCES persons(id),
    CONSTRAINT fk_msglog_campaign FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
    KEY idx_msglog_person     (person_id),
    KEY idx_msglog_campaign   (campaign_id),
    KEY idx_msglog_sent_at    (sent_at)
) ENGINE=InnoDB;

-- ============================================================
-- system_config — non-secret operational settings only
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    config_key      VARCHAR(100) PRIMARY KEY,
    config_value    VARCHAR(500) NOT NULL,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ============================================================
-- designation_catalog — standardized title suggestions
-- ============================================================
CREATE TABLE IF NOT EXISTS designation_catalog (
    id              BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    category        ENUM(
                        'billionaire','millionaire','tech_founder','politician',
                        'content_creator','journalist','human_rights','government_org',
                        'government_official','diplomat','media_personality',
                        'united_organization','high_value_person','other'
                    ) NOT NULL,
    standard_title  VARCHAR(150) NOT NULL,
    UNIQUE KEY uq_catalog_category_title (category, standard_title)
) ENGINE=InnoDB;

-- ============================================================
-- Seed data
-- ============================================================

-- tone_settings default (60/30/10)
INSERT IGNORE INTO tone_settings (id, professional_percent, semi_casual_percent, casual_percent, is_active, updated_by_note)
VALUES (1, 60, 30, 10, TRUE, 'default seed row');

-- system_config defaults
INSERT INTO system_config (config_key, config_value) VALUES
    ('max_words_per_message', '200'),
    ('allow_emoji',           'false'),
    ('default_from_name',     'Meridian Desk'),
    ('send_rate_per_minute',  '20')
ON DUPLICATE KEY UPDATE config_value = VALUES(config_value);

-- designation_catalog seed (Section 19.2)
INSERT IGNORE INTO designation_catalog (category, standard_title) VALUES
-- Billionaire
('billionaire','Chairman & Founder'),
('billionaire','Chairman Emeritus'),
('billionaire','Executive Chairman'),
('billionaire','Principal Owner'),
('billionaire','Family Office Principal'),
('billionaire','Managing Partner, Family Office'),
('billionaire','Sovereign Wealth Fund Governor'),
('billionaire','Private Investment Office Principal'),
('billionaire','Philanthropic Foundation Chair'),
('billionaire','Estate & Legacy Trustee'),
-- Millionaire
('millionaire','Managing Director'),
('millionaire','Principal, Private Equity'),
('millionaire','General Partner, Venture Capital'),
('millionaire','Portfolio Manager'),
('millionaire','Independent Investor'),
('millionaire','Angel Investor'),
('millionaire','Family Business Owner'),
('millionaire','Managing Partner'),
-- Tech Founder
('tech_founder','Founder & CEO'),
('tech_founder','Co-Founder & CTO'),
('tech_founder','Founder & President'),
('tech_founder','Chief Executive Officer'),
('tech_founder','Chief Technology Officer'),
('tech_founder','Chief Product Officer'),
('tech_founder','Chief Operating Officer'),
('tech_founder','Chairman & CEO'),
('tech_founder','Serial Entrepreneur'),
('tech_founder','Startup Studio Founder'),
('tech_founder','Venture Partner'),
-- Politician
('politician','President'),
('politician','Vice President'),
('politician','Prime Minister'),
('politician','Deputy Prime Minister'),
('politician','Senator'),
('politician','Member of Parliament'),
('politician','Member of Congress'),
('politician','Governor'),
('politician','Mayor'),
('politician','State/Provincial Minister'),
('politician','Cabinet Minister'),
('politician','Party Leader'),
('politician','Opposition Leader'),
('politician','City Council Member'),
-- Content Creator
('content_creator','YouTuber / Channel Owner'),
('content_creator','Independent Podcast Host'),
('content_creator','Newsletter Publisher'),
('content_creator','Streaming Creator'),
('content_creator','Social Media Creator'),
('content_creator','Digital Publisher'),
('content_creator','Online Educator'),
('content_creator','Creator-Economy Founder'),
-- Journalist
('journalist','Editor-in-Chief'),
('journalist','Managing Editor'),
('journalist','Senior Correspondent'),
('journalist','Foreign Correspondent'),
('journalist','Investigative Reporter'),
('journalist','Bureau Chief'),
('journalist','News Anchor'),
('journalist','Columnist'),
('journalist','Contributing Editor'),
('journalist','Op-Ed Editor'),
('journalist','Photojournalist'),
-- Human Rights
('human_rights','Human Rights Defender'),
('human_rights','Executive Director, NGO'),
('human_rights','Advocacy Director'),
('human_rights','UN Special Rapporteur'),
('human_rights','Field Director'),
('human_rights','Legal Counsel, Human Rights Organization'),
('human_rights','Campaign Director'),
('human_rights','Policy Director, Human Rights'),
-- Government Organization
('government_org','Agency Director'),
('government_org','Director-General'),
('government_org','Commissioner'),
('government_org','Regulatory Chair'),
('government_org','Executive Secretary'),
('government_org','Program Director'),
('government_org','Bureau Director'),
('government_org','Inspector-General'),
-- Government Official
('government_official','Cabinet Secretary'),
('government_official','Undersecretary'),
('government_official','Permanent Secretary'),
('government_official','Chief of Staff'),
('government_official','Policy Advisor'),
('government_official','Director of Communications'),
('government_official','Deputy Minister'),
('government_official','Attorney General'),
('government_official','Central Bank Governor'),
-- Diplomat
('diplomat','Ambassador'),
('diplomat','Deputy Chief of Mission'),
('diplomat','Consul General'),
('diplomat','Permanent Representative to the UN'),
('diplomat','Special Envoy'),
('diplomat','Chargé d''Affaires'),
('diplomat','Foreign Service Officer'),
('diplomat','Trade Commissioner'),
-- Media Personality
('media_personality','Television Host'),
('media_personality','Radio Host'),
('media_personality','News Presenter'),
('media_personality','Talk Show Host'),
('media_personality','Documentary Presenter'),
('media_personality','Media Commentator'),
('media_personality','Broadcast Personality'),
-- United Organization
('united_organization','Secretary-General'),
('united_organization','Deputy Secretary-General'),
('united_organization','Under-Secretary-General'),
('united_organization','Assistant Secretary-General'),
('united_organization','Special Representative'),
('united_organization','Resident Coordinator'),
('united_organization','Program Director, UN Agency'),
('united_organization','Regional Director'),
-- High Value Person
('high_value_person','Board Chair'),
('high_value_person','Board Member'),
('high_value_person','Senior Advisor'),
('high_value_person','Distinguished Fellow'),
('high_value_person','Executive Advisor'),
('high_value_person','Strategic Advisor');
