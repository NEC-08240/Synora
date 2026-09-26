# Synora Wireframe Plan

## Purpose

This document defines the initial structural layout of the Synora screens
before visual implementation.

The wireframes describe major areas, navigation, and information hierarchy.
Detailed styling and visual implementation will be handled during the
HTML + Tailwind prototyping stage.

---

## SCR-01 — Auth & Gateway

```text
┌─────────────────────────────────────────────┐
│                  SYNORA                     │
│                                             │
│          Welcome to Synora                  │
│                                             │
│          Email / Username                   │
│          [____________________]             │
│                                             │
│          Password                           │
│          [____________________]             │
│                                             │
│              [ Login ]                      │
│                                             │
│          Authentication feedback            │
└─────────────────────────────────────────────┘

Main focus:

Synora identity
Authentication fields
Login action
Authentication feedback
SCR-02 — Student Learning Hub
┌─────────────────────────────────────────────────────────┐
│ Synora        Dashboard     Assessments     Profile     │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Welcome, Student                                        │
│                                                         │
│ Your Subjects                                           │
│                                                         │
│ ┌──────────┐  ┌──────────┐  ┌────────────┐             │
│ │    C     │  │   C++    │  │ DBMS / SQL │             │
│ │ Progress │  │ Progress │  │  Progress  │             │
│ └──────────┘  └──────────┘  └────────────┘             │
│                                                         │
│ Current Learning                                       │
│ Recommended Practice                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘

Main focus:

Subject access
Learning progress
Current learning
Recommended practice
Assessment access
SCR-03 — Interactive Learning Workspace
┌─────────────────────────────────────────────────────────┐
│ Subject | Topic | Mode | AI Status | Profile            │
├──────────────┬────────────────────────┬─────────────────┤
│              │                        │                 │
│ Learning     │ Practical Workspace    │ AI Companion    │
│ Content      │                        │                 │
│              │ Language / SQL         │ Conversation    │
│ Topic        │ Editor                 │                 │
│ Progress     │                        │ Voice Controls  │
│ Objectives   │ Run / Submit           │                 │
│ Resources    │                        │                 │
│              │ Output / Results       │                 │
├──────────────┴────────────────────────┴─────────────────┤
│ Execution / Session Status                              │
└─────────────────────────────────────────────────────────┘

Main focus:

Learning content
Practical work
Execution results
Contextual AI interaction
Voice interaction
Session status
SCR-04 — Student Assessment Arena
┌─────────────────────────────────────────────────────────┐
│ Synora | Assessment | Progress | Student                │
├─────────────────────────────────────────────────────────┤
│ Assessment Title                                        │
│ Instructions                                            │
│                                                         │
│ Question / Task                                         │
│                                                         │
│ [ Answer / Code / SQL Area ]                            │
│                                                         │
│ [ Run ]                         [ Submit ]              │
│                                                         │
│ Progress / Attempt Status                               │
│                                                         │
│ Results / Feedback                                      │
└─────────────────────────────────────────────────────────┘

Main focus:

Assessment instructions
Questions/tasks
Answer or practical workspace
Submission
Attempt/progress state
Results/feedback
SCR-05 — Faculty Authoring Studio
┌─────────────────────────────────────────────────────────┐
│ Synora | Faculty | Courses | Profile                    │
├──────────────────┬──────────────────────────────────────┤
│                  │                                      │
│ Course Structure │ Content Editor                       │
│                  │                                      │
│ Subject          │ Lesson / Topic Content               │
│   └ Topic        │                                      │
│      └ Lesson    │ Objectives / Resources               │
│                  │                                      │
│ Quiz             │ Quiz / Practical Task Configuration  │
│ Practical Task   │                                      │
│                  │                                      │
└──────────────────┴──────────────────────────────────────┘

Main focus:

Course hierarchy
Lesson authoring
Learning objectives/resources
Quiz creation
Practical task creation
Content management
SCR-06 — Faculty Grading & Monitoring
┌─────────────────────────────────────────────────────────┐
│ Synora | Faculty | Grading | Monitoring                 │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Student / Course / Assessment Filters                   │
│                                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Student Submission / Assessment List                │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ Selected Submission                                     │
│ ┌──────────────────────────┬──────────────────────────┐ │
│ │ Student Work             │ Grade / Feedback         │ │
│ │ Code / Answers / SQL     │                          │ │
│ └──────────────────────────┴──────────────────────────┘ │
│                                                         │
│ Student / Batch Progress                                │
└─────────────────────────────────────────────────────────┘

Main focus:

Submission review
Grading
Feedback
Student progress
Monitoring information
SCR-07 — Admin Platform Console
┌─────────────────────────────────────────────────────────┐
│ Synora | Admin Console | Profile                        │
├──────────────────┬──────────────────────────────────────┤
│                  │                                      │
│ Administration   │ Management Area                      │
│                  │                                      │
│ Users            │ Selected management function         │
│ Roles            │                                      │
│ Subjects         │ Users / Roles / Subjects              │
│ Configuration    │                                      │
│                  │                                      │
└──────────────────┴──────────────────────────────────────┘

Main focus:

User management
Role management
Subject management
Platform-level configuration
Navigation Overview
Student
SCR-01
  ↓
SCR-02
  ├── SCR-03
  └── SCR-04
Faculty
SCR-01
  ↓
SCR-05
  ↓
SCR-06
Administrator
SCR-01
  ↓
SCR-07
Design Note

These wireframes represent the initial structural direction only.

During HTML + Tailwind prototyping, layouts, navigation, component placement,
and information hierarchy may be refined based on usability and team review.

The wireframes do not define final colors, typography, animations, or detailed
component styling.