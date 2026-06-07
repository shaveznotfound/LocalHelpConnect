-- ══════════════════════════════════════════════════════════════════
--  Local Help Connect v6 — Full Schema & Migration Script
--  Run this to create the database fresh, OR migrate from lhc_v5.
-- ══════════════════════════════════════════════════════════════════

-- 1. Create database
CREATE DATABASE IF NOT EXISTS `lhc_v7`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `lhc_v7`;

-- 2. Users (added avatar_url)
CREATE TABLE IF NOT EXISTS users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  full_name     VARCHAR(100) NOT NULL,
  phone         VARCHAR(20)  NOT NULL UNIQUE,
  email         VARCHAR(120) DEFAULT NULL,
  password_hash VARCHAR(256) NOT NULL,
  role          ENUM('customer','worker') NOT NULL,
  is_admin      TINYINT(1)   NOT NULL DEFAULT 0,
  is_banned     TINYINT(1)   NOT NULL DEFAULT 0,
  avatar_url    VARCHAR(300) DEFAULT NULL,
  login_attempts INT NOT NULL DEFAULT 0,
  locked_until  TIMESTAMP NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Worker profiles
CREATE TABLE IF NOT EXISTS worker_profiles (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT NOT NULL UNIQUE,
  skills       VARCHAR(500) DEFAULT NULL,
  experience   VARCHAR(200) DEFAULT NULL,
  description  TEXT DEFAULT NULL,
  location     VARCHAR(200) DEFAULT NULL,
  lat          DECIMAL(10,7) DEFAULT NULL,
  lng          DECIMAL(10,7) DEFAULT NULL,
  availability ENUM('available','busy','offline') NOT NULL DEFAULT 'available',
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Worker availability (blocked dates)
CREATE TABLE IF NOT EXISTS worker_availability (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  worker_id    INT NOT NULL,
  blocked_date DATE NOT NULL,
  reason       VARCHAR(200) DEFAULT NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_worker_date (worker_id, blocked_date),
  FOREIGN KEY (worker_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. Job requests (added request_code)
CREATE TABLE IF NOT EXISTS job_requests (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  request_code     VARCHAR(20) NOT NULL UNIQUE,
  customer_id      INT NOT NULL,
  worker_id        INT NOT NULL,
  description      TEXT NOT NULL,
  location         VARCHAR(200) NOT NULL,
  category         VARCHAR(100) DEFAULT NULL,
  customer_budget  DECIMAL(10,2) DEFAULT NULL,
  worker_counter   DECIMAL(10,2) DEFAULT NULL,
  price_status     ENUM('open','countered','agreed') NOT NULL DEFAULT 'open',
  scheduled_at     DATETIME DEFAULT NULL,
  status           ENUM('pending','accepted','rejected') NOT NULL DEFAULT 'pending',
  job_stage        ENUM('accepted','on_the_way','arrived','in_progress','completed') DEFAULT NULL,
  stage_updated_at TIMESTAMP NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (worker_id)   REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Posted jobs
CREATE TABLE IF NOT EXISTS posted_jobs (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  customer_id INT NOT NULL,
  title       VARCHAR(200) NOT NULL,
  description TEXT NOT NULL,
  location    VARCHAR(200) NOT NULL,
  category    VARCHAR(100) DEFAULT NULL,
  status      ENUM('open','closed') NOT NULL DEFAULT 'open',
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. Chat messages (upgraded: msg_type, file_url, file_name, file_size)
CREATE TABLE IF NOT EXISTS chat_messages (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  request_id   INT NOT NULL,
  sender_id    INT NOT NULL,
  message      TEXT DEFAULT NULL,
  msg_type     ENUM('text','image','file') NOT NULL DEFAULT 'text',
  file_url     VARCHAR(300) DEFAULT NULL,
  file_name    VARCHAR(200) DEFAULT NULL,
  file_size    INT DEFAULT NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (request_id) REFERENCES job_requests(id) ON DELETE CASCADE,
  FOREIGN KEY (sender_id)  REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. Ratings
CREATE TABLE IF NOT EXISTS ratings (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  request_id            INT NOT NULL UNIQUE,
  customer_id           INT NOT NULL,
  worker_id             INT NOT NULL,
  rating                TINYINT NOT NULL,
  rating_punctuality    TINYINT DEFAULT NULL,
  rating_quality        TINYINT DEFAULT NULL,
  rating_communication  TINYINT DEFAULT NULL,
  review                TEXT DEFAULT NULL,
  created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (request_id)  REFERENCES job_requests(id) ON DELETE CASCADE,
  FOREIGN KEY (customer_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (worker_id)   REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. Reports
CREATE TABLE IF NOT EXISTS reports (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  reporter_id INT NOT NULL,
  reported_id INT NOT NULL,
  reason      VARCHAR(100) NOT NULL,
  details     TEXT DEFAULT NULL,
  status      ENUM('pending','reviewed','dismissed') NOT NULL DEFAULT 'pending',
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (reported_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ══════════════════════════════════════════════════════════════════
--  MIGRATION: If upgrading from lhc_v5 use these ALTER statements
-- ══════════════════════════════════════════════════════════════════

-- ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(300) DEFAULT NULL AFTER is_banned;
-- ALTER TABLE job_requests ADD COLUMN IF NOT EXISTS request_code VARCHAR(20) AFTER id;
-- ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS msg_type ENUM('text','image','file') NOT NULL DEFAULT 'text' AFTER message;
-- ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url VARCHAR(300) DEFAULT NULL AFTER msg_type;
-- ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_name VARCHAR(200) DEFAULT NULL AFTER file_url;
-- ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_size INT DEFAULT NULL AFTER file_name;
-- UPDATE job_requests SET request_code = CONCAT('REQ', YEAR(created_at), LPAD(id, 4, '0')) WHERE request_code IS NULL OR request_code = '';
-- ALTER TABLE job_requests ADD UNIQUE KEY uq_req_code (request_code);

-- ══════════════════════════════════════════════════════════════════
--  v7 MIGRATION: Price negotiation + expanded categories
-- ══════════════════════════════════════════════════════════════════
-- Run these ALTER statements when upgrading from v6:
-- ALTER TABLE job_requests ADD COLUMN IF NOT EXISTS customer_budget DECIMAL(10,2) DEFAULT NULL AFTER category;
-- ALTER TABLE job_requests ADD COLUMN IF NOT EXISTS worker_counter  DECIMAL(10,2) DEFAULT NULL AFTER customer_budget;
-- ALTER TABLE job_requests ADD COLUMN IF NOT EXISTS price_status ENUM('open','countered','agreed') NOT NULL DEFAULT 'open' AFTER worker_counter;
