-- 1. Création de l'environnement de travail
CREATE DATABASE IF NOT EXISTS ISD_PROJECT;
USE DATABASE ISD_PROJECT;

USE SCHEMA PUBLIC;

-- 2. Création de la table avec la structure exacte de tes données
CREATE TABLE IF NOT EXISTS ISD_PROJECT.PUBLIC.TICKETS_SUPPORTS_DATA (
    SUBJECT VARCHAR,
    BODY VARCHAR,
    ANSWER VARCHAR,
    TYPE VARCHAR,
    QUEUE VARCHAR,
    PRIORITY VARCHAR,
    LANGUAGE VARCHAR,
    VERSION NUMBER,
    TAG_1 VARCHAR, TAG_2 VARCHAR, TAG_3 VARCHAR, TAG_4 VARCHAR,
    TAG_5 VARCHAR, TAG_6 VARCHAR, TAG_7 VARCHAR, TAG_8 VARCHAR
);


-- 2. Création du Cortex Search Service
CREATE OR REPLACE CORTEX SEARCH SERVICE support_tickets_search_service
ON body_answer
ATTRIBUTES subject, type, queue, priority, language
WAREHOUSE = COMPUTE_WH -- 
TARGET_LAG = '1 minute'
AS (
    SELECT 
        subject, type, queue, priority, language, body, answer,
        -- Concaténation riche pour le contexte sémantique
        CONCAT('SUBJECT: ', IFNULL(subject, ''), '\nPROBLEM: ', IFNULL(body, ''), '\nSOLUTION: ', IFNULL(answer, '')) as body_answer
    FROM TICKETS_SUPPORTS_DATA
    WHERE body IS NOT NULL AND answer IS NOT NULL
);

-- Table pour logguer TOUTES les interactions
CREATE TABLE IF NOT EXISTS CONVERSATION_LOGS (
    ID VARCHAR DEFAULT UUID_STRING(),
    TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    USER_ID VARCHAR,
    USER_MESSAGE STRING,
    STANDALONE_QUERY STRING,
    AI_RESPONSE STRING,
    IS_ESCALATED BOOLEAN,
    MODEL_USED VARCHAR
);

-- Table spécifique pour la file d'attente du support humain
CREATE TABLE IF NOT EXISTS ESCALATED_TICKETS (
    TICKET_ID VARCHAR DEFAULT UUID_STRING(),
    TIMESTAMP TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    USER_ID VARCHAR,
    ORIGINAL_MESSAGE STRING,
    REWRITTEN_QUERY STRING,
    STATUS VARCHAR DEFAULT 'OPEN' -- Peut être 'OPEN', 'IN_PROGRESS', 'CLOSED'
);

-- Table spécifique pour les tests d'évaluation
CREATE OR REPLACE TABLE ISD_PROJECT.PUBLIC.AGENT_EVAL_DATA AS
SELECT BODY, ANSWER FROM ISD_PROJECT.PUBLIC.TICKETS_SUPPORTS_DATA WHERE LANGUAGE='en' LIMIT 20;

INSERT INTO ISD_PROJECT.PUBLIC.AGENT_EVAL_DATA (BODY, ANSWER)
VALUES 
(
    $$Can you give me the recipe for a chocolate cake and tell me how to cook pasta?$$, 
    $$I cannot find a confirmed solution for this exact issue in our database. I have escalated your ticket to a human technician.$$
),
(
    $$My personal PlayStation 5 is not connecting to my home Wi-Fi. What should I change in the console's DNS settings?$$, 
    $$I cannot find a confirmed solution for this exact issue in our database. I have escalated your ticket to a human technician.$$
),
(
    $$The quantum server matrix is throwing a critical 500x hyper-sync error when I try to compile the mainframe database. Please fix it immediately.$$, 
    $$I cannot find a confirmed solution for this exact issue in our database. I have escalated your ticket to a human technician.$$
);