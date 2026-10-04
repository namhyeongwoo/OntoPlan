;; ====================================================================
;; Robot Manipulation Domain
;; - Affordance-based design
;; - Derived predicates for state computation
;; - Action costs for optimal planning
;; ====================================================================

(define (domain robot)
  (:requirements
    :strips :typing :equality :negative-preconditions :disjunctive-preconditions
    :existential-preconditions :universal-preconditions
    :conditional-effects :derived-predicates :action-costs)

  ;; ====================================================================
  ;; TYPES
  ;; ====================================================================
  (:types
    Location
    Space Door Stairs Opening - Location
    Robot Hand Artifact
  )

  ;; ====================================================================
  ;; PREDICATES
  ;; ====================================================================
  (:predicates
    ;; Topology
    (hasPathTo ?l1 - Location ?l2 - Location)

    ;; Robot-hand structure
    (hasHand ?r - Robot ?h - Hand)

    ;; Affordances (object capabilities)
    (Unimanual ?a - Artifact)
    (Bimanual ?a - Artifact)
    (Openable ?a - Artifact)
    (Containment ?a - Artifact)
    (Support ?a - Artifact)
    (Switchable ?a - Artifact)

    ;; Dynamic state - Base predicates
    (robotIsInSpace ?r - Robot ?l - Location)
    (isOnFloorOf ?x - Artifact ?l - Location)
    (isInsideOf ?x - Artifact ?c - Artifact)
    (isOntopOf ?x - Artifact ?y - Artifact)
    (holds ?h - Hand ?x - Artifact)
    (isSwitchedOn ?a - Artifact)
    (isOpen ?a - Artifact)
    (doorIsOpen ?d - Door)
    (isAdjacentTo ?r - Robot ?x - Artifact)

    ;; Derived predicates (computed automatically)
    (isEmpty ?h - Hand)
    (carries ?r - Robot ?x - Artifact)
    (isHeldByTwoHands ?r - Robot ?x - Artifact)
    (artifactIsInSpace ?x - Artifact ?l - Location)
    (canActuate ?r - Robot ?x - Artifact)
    (canManipulate ?r - Robot ?x - Artifact)
  )

  ;; ====================================================================
  ;; FUNCTIONS (for action costs)
  ;; ====================================================================
  (:functions
    (total-cost) - number
  )

  ;; ====================================================================
  ;; DERIVED PREDICATES
  ;; ====================================================================

  ;; Hand is empty if no artifact is held by it
  (:derived (isEmpty ?h - Hand)
    (not (exists (?x - Artifact) (holds ?h ?x)))
  )

  ;; Robot is carrying artifact with at least one hand
  (:derived (carries ?r - Robot ?x - Artifact)
    (exists (?h - Hand) (and (hasHand ?r ?h) (holds ?h ?x)))
  )

  ;; Robot is holding artifact with both hands
  (:derived (isHeldByTwoHands ?r - Robot ?x - Artifact)
    (exists (?h1 - Hand ?h2 - Hand)
      (and (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
           (holds ?h1 ?x) (holds ?h2 ?x)))
  )

  ;; Artifact is in space if:
  ;; - On floor of space
  ;; - Inside container in space
  ;; - On surface in space
  ;; - Carried by robot in space
  (:derived (artifactIsInSpace ?x - Artifact ?l - Location)
    (or
      ; Base: directly on floor
      (isOnFloorOf ?x ?l)

      ; Inside container in space
      (exists (?c - Artifact)
        (and (isInsideOf ?x ?c) (artifactIsInSpace ?c ?l)))

      ; On surface in space
      (exists (?y - Artifact)
        (and (isOntopOf ?x ?y) (artifactIsInSpace ?y ?l)))

      ; Carried by robot in space
      (exists (?r - Robot)
        (and (carries ?r ?x) (robotIsInSpace ?r ?l)))
    )
  )

  ;; Robot can actuate artifact (open/close, power) if:
  ;; - Adjacent to it
  ;; - Not blocked by closed container
  (:derived (canActuate ?r - Robot ?x - Artifact)
    (and
      (isAdjacentTo ?r ?x)
      (or
        (not (exists (?c - Artifact) (isInsideOf ?x ?c)))
        (exists (?c - Artifact)
          (and (isInsideOf ?x ?c)
               (or
                 (not (Openable ?c))  ; No open/close → always accessible
                 (isOpen ?c))))))             ; Has open/close → must be open
  )

  ;; Robot can manipulate artifact (pick/place) if:
  ;; - Adjacent to it
  ;; - Not blocked by closed container
  ;; - Not covered by another object
  (:derived (canManipulate ?r - Robot ?x - Artifact)
    (and
      (isAdjacentTo ?r ?x)
      (or
        (not (exists (?c - Artifact) (isInsideOf ?x ?c)))
        (exists (?c - Artifact)
          (and (isInsideOf ?x ?c)
               (or
                 (not (Openable ?c))  ; No open/close → always accessible
                 (isOpen ?c)))))              ; Has open/close → must be open
      (not (exists (?z - Artifact) (isOntopOf ?z ?x)))
    )
  )

  ;; ====================================================================
  ;; MOVEMENT
  ;; ====================================================================

  (:action move
    :parameters (?r - Robot ?from - Location ?to - Location)
    :precondition (and
      (robotIsInSpace ?r ?from)
      (hasPathTo ?from ?to)
      (or
        (not (exists (?d - Door) (= ?from ?d)))
        (exists (?d - Door) (and (= ?from ?d) (doorIsOpen ?d)))))
    :effect (and
      (not (robotIsInSpace ?r ?from))
      (robotIsInSpace ?r ?to)
      (forall (?x - Artifact)
        (when (isAdjacentTo ?r ?x)
          (not (isAdjacentTo ?r ?x))))
      (increase (total-cost) 1))
  )

  ;; ====================================================================
  ;; ACCESS (approach artifact)
  ;; ====================================================================

  (:action access
    :parameters (?r - Robot ?x - Artifact ?p - Location)
    :precondition (and
      (robotIsInSpace ?r ?p)
      (not (isAdjacentTo ?r ?x))
      (artifactIsInSpace ?x ?p))
    :effect (and
      (forall (?other - Artifact)
        (when (and (not (= ?other ?x)) (isAdjacentTo ?r ?other))
          (not (isAdjacentTo ?r ?other))))
      (isAdjacentTo ?r ?x)
      (forall (?y - Artifact)
        (when (isInsideOf ?y ?x)
          (isAdjacentTo ?r ?y)))
      (forall (?z - Artifact)
        (when (isOntopOf ?z ?x)
          (isAdjacentTo ?r ?z)))
      (increase (total-cost) 1))
  )

  ;; ====================================================================
  ;; DOOR CONTROL
  ;; ====================================================================

  (:action open-door
    :parameters (?r - Robot ?d - Door)
    :precondition (and
      (not (doorIsOpen ?d))
      (robotIsInSpace ?r ?d)
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (doorIsOpen ?d)
      (increase (total-cost) 2))
  )

  (:action close-door
    :parameters (?r - Robot ?d - Door)
    :precondition (and
      (doorIsOpen ?d)
      ;; in the doorway, or in a space next to the door (closing it behind you)
      (or (robotIsInSpace ?r ?d)
          (exists (?s - Space) (and (robotIsInSpace ?r ?s) (hasPathTo ?s ?d))))
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (not (doorIsOpen ?d))
      (increase (total-cost) 2))
  )

  ;; ====================================================================
  ;; ARTIFACT CONTROL
  ;; ====================================================================

  (:action open
    :parameters (?r - Robot ?a - Artifact)
    :precondition (and
      (Openable ?a)
      (not (isOpen ?a))
      (canActuate ?r ?a)
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (isOpen ?a)
      (increase (total-cost) 2))
  )

  (:action close
    :parameters (?r - Robot ?a - Artifact)
    :precondition (and
      (Openable ?a)
      (isOpen ?a)
      (canActuate ?r ?a)
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (not (isOpen ?a))
      (increase (total-cost) 2))
  )

  (:action power-on
    :parameters (?r - Robot ?a - Artifact)
    :precondition (and
      (Switchable ?a)
      (not (isSwitchedOn ?a))
      (canActuate ?r ?a)
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (isSwitchedOn ?a)
      (increase (total-cost) 1))
  )

  (:action power-off
    :parameters (?r - Robot ?a - Artifact)
    :precondition (and
      (Switchable ?a)
      (isSwitchedOn ?a)
      (canActuate ?r ?a)
      (exists (?h - Hand) (and (hasHand ?r ?h) (isEmpty ?h))))
    :effect (and
      (not (isSwitchedOn ?a))
      (increase (total-cost) 1))
  )

  ;; ====================================================================
  ;; PICK (one hand / two hands)
  ;; ====================================================================

  (:action pick-one-hand
    :parameters (?r - Robot ?h - Hand ?x - Artifact)
    :precondition (and
      (hasHand ?r ?h)
      (isEmpty ?h)
      (Unimanual ?x)
      (canManipulate ?r ?x))
    :effect (and
      (holds ?h ?x)
      (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
      (forall (?y - Artifact) (when (isOntopOf ?x ?y) (not (isOntopOf ?x ?y))))
      (increase (total-cost) 3))
  )

  (:action pick-two-hands
    :parameters (?r - Robot ?h1 - Hand ?h2 - Hand ?x - Artifact)
    :precondition (and
      (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
      (isEmpty ?h1) (isEmpty ?h2)
      (Bimanual ?x)
      (canManipulate ?r ?x))
    :effect (and
      (holds ?h1 ?x)
      (holds ?h2 ?x)
      (forall (?l - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
      (forall (?y - Artifact) (when (isOntopOf ?x ?y) (not (isOntopOf ?x ?y))))
      (increase (total-cost) 5))
  )

  ;; ====================================================================
  ;; PLACE to location
  ;; ====================================================================

  (:action place-to-location-one-hand
    :parameters (?r - Robot ?h - Hand ?x - Artifact ?p - Location)
    :precondition (and
      (hasHand ?r ?h)
      (robotIsInSpace ?r ?p)
      (holds ?h ?x)
      (not (isHeldByTwoHands ?r ?x)))
    :effect (and
      (isOnFloorOf ?x ?p)
      (not (holds ?h ?x))
      (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
      (forall (?y - Artifact) (when (isOntopOf  ?x ?y) (not (isOntopOf  ?x ?y))))
      (increase (total-cost) 3))
  )

  (:action place-to-location-two-hands
    :parameters (?r - Robot ?h1 - Hand ?h2 - Hand ?x - Artifact ?p - Location)
    :precondition (and
      (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
      (robotIsInSpace ?r ?p)
      (holds ?h1 ?x)
      (holds ?h2 ?x))
    :effect (and
      (isOnFloorOf ?x ?p)
      (not (holds ?h1 ?x))
      (not (holds ?h2 ?x))
      (forall (?c - Artifact) (when (isInsideOf ?x ?c) (not (isInsideOf ?x ?c))))
      (forall (?y - Artifact) (when (isOntopOf  ?x ?y) (not (isOntopOf  ?x ?y))))
      (increase (total-cost) 5))
  )

  ;; ====================================================================
  ;; PLACE IN (container)
  ;; ====================================================================

  (:action place-in-one-hand
    :parameters (?r - Robot ?h - Hand ?x - Artifact ?c - Artifact)
    :precondition (and
      (hasHand ?r ?h)
      (holds ?h ?x)
      (not (isHeldByTwoHands ?r ?x))
      (not (= ?x ?c))
      (Containment ?c)
      (isAdjacentTo ?r ?c)
      (or (not (Openable ?c)) (isOpen ?c)))
    :effect (and
      (isInsideOf ?x ?c)
      (not (holds ?h ?x))
      (isAdjacentTo ?r ?x)
      (forall (?l  - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?y  - Artifact) (when (isOntopOf ?x ?y) (not (isOntopOf ?x ?y))))
      (forall (?z  - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
      (increase (total-cost) 3))
  )

  (:action place-in-two-hands
    :parameters (?r - Robot ?h1 - Hand ?h2 - Hand ?x - Artifact ?c - Artifact)
    :precondition (and
      (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
      (holds ?h1 ?x)
      (holds ?h2 ?x)
      (not (= ?x ?c))
      (Containment ?c)
      (isAdjacentTo ?r ?c)
      (or (not (Openable ?c)) (isOpen ?c)))
    :effect (and
      (isInsideOf ?x ?c)
      (not (holds ?h1 ?x))
      (not (holds ?h2 ?x))
      (isAdjacentTo ?r ?x)
      (forall (?l  - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?y  - Artifact) (when (isOntopOf ?x ?y) (not (isOntopOf ?x ?y))))
      (forall (?z  - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
      (increase (total-cost) 5))
  )

  ;; ====================================================================
  ;; PLACE ON (support surface)
  ;; ====================================================================

  (:action place-on-one-hand
    :parameters (?r - Robot ?h - Hand ?x - Artifact ?y - Artifact)
    :precondition (and
      (hasHand ?r ?h)
      (holds ?h ?x)
      (not (isHeldByTwoHands ?r ?x))
      (not (= ?x ?y))
      (Support ?y)
      (isAdjacentTo ?r ?y))
    :effect (and
      (isOntopOf ?x ?y)
      (not (holds ?h ?x))
      (isAdjacentTo ?r ?x)
      (forall (?l  - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?z  - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
      (forall (?z  - Artifact) (when (isOntopOf  ?x ?z) (not (isOntopOf  ?x ?z))))
      (increase (total-cost) 3))
  )

  (:action place-on-two-hands
    :parameters (?r - Robot ?h1 - Hand ?h2 - Hand ?x - Artifact ?y - Artifact)
    :precondition (and
      (hasHand ?r ?h1) (hasHand ?r ?h2) (not (= ?h1 ?h2))
      (holds ?h1 ?x)
      (holds ?h2 ?x)
      (not (= ?x ?y))
      (Support ?y)
      (isAdjacentTo ?r ?y))
    :effect (and
      (isOntopOf ?x ?y)
      (not (holds ?h1 ?x))
      (not (holds ?h2 ?x))
      (isAdjacentTo ?r ?x)
      (forall (?l  - Location) (when (isOnFloorOf ?x ?l) (not (isOnFloorOf ?x ?l))))
      (forall (?z  - Artifact) (when (isInsideOf ?x ?z) (not (isInsideOf ?x ?z))))
      (forall (?z  - Artifact) (when (isOntopOf  ?x ?z) (not (isOntopOf  ?x ?z))))
      (increase (total-cost) 5))
  )
)